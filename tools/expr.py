import re

VERBOSE_SIMPLIFY = False

type_to_idx = {bool: 0, int: 1, float:2}
idx_to_type = [bool, int, float]

def coerce_types(*args):
    dtype_indices = [type_to_idx[dtype(arg)] for arg in args]
    return idx_to_type[max(dtype_indices)]

def dtype(expr):
    return expr.dtype() if isinstance(expr, Expr) else type(expr)

def collect_variables(expr):
    if isinstance(expr, Expr):
        return expr.collect_variables()
    else:
        return set()

def simplify(expr):
    simplified = expr.simplify() if isinstance(expr, Expr) else expr
    while simplified is not expr:
        if VERBOSE_SIMPLIFY:
            print """simplifying
%s
to
%s
""" % (expr, simplified) 
        expr = simplified
        simplified = expr.simplify() if isinstance(expr, Expr) else expr
    return simplified

def as_string(expr, indent):
    if isinstance(expr, Expr):
         return expr.as_string(indent)
    elif isinstance(expr, float):
        return str(expr)
    else:
        return repr(expr)

def isequal(expr, other):
    if isinstance(expr, Expr):
        return expr.isequal(other)
    elif isinstance(other, Expr):
        return other.isequal(expr)
    else:
        return expr == other
        
class Expr(object):
    def __lt__(self, other):
        return ComparisonOp('<', self, other)
    def __le__(self, other):
        return LowerOrEqual('<=', self, other)
    def __eq__(self, other):
        return Equality('==', self, other)
    def __ne__(self, other):
        return Inequality('!=', self, other)
    def __gt__(self, other):
        return ComparisonOp('>', self, other)
    def __ge__(self, other):
        return GreaterOrEqual('>=', self, other)
    
    def __add__(self, other):
        return Addition('+', self, other)
    def __sub__(self, other):
        return Substraction('-', self, other)
    def __mul__(self, other):
        return Multiplication('*', self, other)
    def __div__(self, other):
        return Division('/', self, other)
    def __truediv__(self, other):
        return Division('/', self, other)
    def __floordiv__(self, other):
        return Division('//', self, other)
    def __mod__(self, other):
        return BinaryOp('%', self, other)
    def __divmod__(self, other):
        #FIXME
        return BinaryOp('divmod', self, other)
    def __pow__(self, other, modulo=None):
        return BinaryOp('**', self, other)
    def __lshift__(self, other):
        return BinaryOp('<<', self, other)
    def __rshift__(self, other):
        return BinaryOp('>>', self, other)
    
    def __and__(self, other):
        return And('&', self, other)
    def __xor__(self, other):
        return BinaryOp('^', self, other)
    def __or__(self, other):
        return Or('|', self, other)
    
    def __radd__(self, other):
        return Addition('+', other, self)
    def __rsub__(self, other):
        return Substraction('-', other, self)
    def __rmul__(self, other):
        return Multiplication('*', other, self)
    def __rdiv__(self, other):
        return Division('/', other, self)
    def __rtruediv__(self, other):
        return Division('/', other, self)
    def __rfloordiv__(self, other):
        return Division('//', other, self)
    def __rmod__(self, other):
        return BinaryOp('%', other, self)
    def __rdivmod__(self, other):
        return BinaryOp('divmod', other, self)
    def __rpow__(self, other):
        return BinaryOp('**', other, self)
    def __rlshift__(self, other):
        return BinaryOp('<<', other, self)
    def __rrshift__(self, other):
        return BinaryOp('>>', other, self)
    
    def __rand__(self, other):
        return And('&', other, self)
    def __rxor__(self, other):
        return BinaryOp('^', other, self)
    def __ror__(self, other):
        return Or('|', other, self)
        
    def __neg__(self):
        return UnaryOp('-', self)
    def __pos__(self):
        return UnaryOp('+', self)
    def __abs__(self):
        return UnaryOp('abs', self)
    def __invert__(self):
        return Not('~', self)
    
    def simplify(self):
        return self

    def as_string(self, indent):
        raise NotImplementedError()

    def __str__(self):
        return self.as_string('')

    __repr__ = __str__

    
class UnaryOp(Expr):
    def __init__(self, op, expr):
        self.op = op
        self.expr = expr
        
    def simplify(self):
        expr = simplify(self.expr)
        if not isinstance(expr, Expr):
            return eval('%s%s' % (self.op, self.expr))
        return self

    def op_str(self):
        return self.op
    
    def as_string(self, indent):
        expr = self.expr
        if not isinstance(expr, Expr) or isinstance(expr, Variable):
            return "%s%s" % (self.op_str(), expr)
        else:
            return "%s(%s)" % (self.op_str(), expr.as_string(indent))

    def collect_variables(self):
        return self.expr.collect_variables()

    def dtype(self):
        return dtype(self.expr)

    def isequal(self, other):
        return isinstance(other, UnaryOp) and self.op == other.op and \
               isequal(self.expr, other.expr)

class Not(UnaryOp):
    def simplify(self):
        expr = simplify(self.expr)
        if not isinstance(expr, Expr):
            return not expr
        elif isinstance(expr, Not):
            return expr.expr
        return self

    def op_str(self):
        return 'not '


class BinaryOp(Expr):
    priority = 0
    commutative = None
    neutral_value = None
    overpowering_value = None

    def __init__(self, op, expr1, expr2):
        self.op = op
        self.expr1 = expr1
        self.expr2 = expr2

    def dtype(self):
        dtype1 = dtype(self.expr1)
        dtype2 = dtype(self.expr2)
        dtype1_idx = type_to_idx[dtype1]
        dtype2_idx = type_to_idx[dtype2]
        res_type_idx = max(dtype1_idx, dtype2_idx)
        return idx_to_type[res_type_idx]

    def needparenthesis(self, expr):
        if not isinstance(expr, BinaryOp):
            return False
#        return True
    
        # theoretically, the commutative part it is only necessary for expr2,
        # but it doesn't decrease readability anyway: 
        # "(a - b) - c" is as readable as "a - b - c"
        return self.priority < expr.priority or (self.op == expr.op and 
                                                 not self.commutative)

    def op_str(self):
        return self.op
    
    def as_string(self, indent):
        # for priorities, see: 
        # http://docs.python.org/reference/expressions.html#summary
        s1 = as_string(self.expr1, indent)
        if self.needparenthesis(self.expr1):
            s1 = "(%s)" % s1
        s2 = as_string(self.expr2, indent)
        if self.needparenthesis(self.expr2):
            s2 = "(%s)" % s2
        return "%s %s %s" % (s1, self.op_str(), s2)

    def simplify(self):
        orig_expr1, orig_expr2 = self.expr1, self.expr2
        expr1, expr2 = simplify(orig_expr1), simplify(orig_expr2)
        if expr1 is not orig_expr1 or expr2 is not orig_expr2:
            return self.__class__(self.op, expr1, expr2)
        
        if self.neutral_value is not None:
            if isinstance(expr1, self.accepted_types) and \
               expr1 == self.neutral_value:
                return expr2
            elif isinstance(expr2, self.accepted_types) and \
               expr2 == self.neutral_value:
                return expr1
            
        if self.overpowering_value is not None:
            if isinstance(expr1, self.accepted_types) and \
               expr1 == self.overpowering_value:
                return self.overpowering_value
            elif isinstance(expr2, self.accepted_types) and \
               expr2 == self.overpowering_value:
                return self.overpowering_value

        if not isinstance(expr1, Expr) and not isinstance(expr2, Expr):
            return eval('%s %s %s' % (expr1, self.op, expr2))

        return self
    
    def collect_variables(self):
        expr1_vars = collect_variables(self.expr1) 
        expr2_vars = collect_variables(self.expr2) 
        return expr1_vars.union(expr2_vars)

    def isequal(self, other):
        return isinstance(other, BinaryOp) and self.op == other.op and \
               isequal(self.expr1, other.expr1) and \
               isequal(self.expr2, other.expr2)

class ComparisonOp(BinaryOp):
    priority = 10

    def dtype(self):
        return bool

    def typecast(self):
        e1, e2 = self.expr1, self.expr2
        if isinstance(e1, Expr) and not isinstance(e2, Expr):
            # type cast constants
            dtype1 = dtype(e1)
            if dtype1 is bool:
                # down cast 0.0 and 1.0 to bool
                assert e2 in (0.0, 1.0), "%s is not in (0, 1)" % e2
                if e2 is not bool(e2):
                    return self.__class__(self.op, e1, bool(e2))
            elif dtype1 is int:
                # down cast 5.0 to int
                assert int(e2) == e2, "trying to compare %s which is an int " \
                                      "to %f which has a fractional part" % \
                                      (e1, e2)
                if e2 is not int(e2):
                    return self.__class__(self.op, e1, int(e2))
            elif dtype1 is float:
                # up cast to float
                if e2 is not float(e2):
                    return self.__class__(self.op, e1, float(e2))
        return self

class LowerOrEqual(ComparisonOp):
    def simplify(self):
        simplified = self.typecast()
        if simplified is not self:
            return simplified
        
        expr1 = simplify(self.expr1)
        expr2 = simplify(self.expr2)
        #TODO: use generic bounds check instead
        if dtype(expr1) is bool:
            if expr2 is True:
                return True
            elif expr2 is False:
                return expr1 == False
        return self

class GreaterOrEqual(ComparisonOp):
    def simplify(self):        
        simplified = self.typecast()
        if simplified is not self:
            return simplified

        expr1 = simplify(self.expr1)
        expr2 = simplify(self.expr2)
        #TODO: use generic bounds check instead
        if dtype(expr1) is bool:
            if expr2 is False:
                return True
            elif expr2 is True:
                return expr1 == True
        return self
    
class Equality(ComparisonOp):
    def simplify(self):
        simplified = self.typecast()
        if simplified is not self:
            return simplified

        expr1 = simplify(self.expr1)
        expr2 = simplify(self.expr2)
        if dtype(expr1) is bool:
            if expr2 is True:
                return expr1
            elif expr2 is False:
                return ~expr1
        return self

class Inequality(ComparisonOp):
    def simplify(self):
        simplified = self.typecast()
        if simplified is not self:
            return simplified

        expr1 = simplify(self.expr1)
        expr2 = simplify(self.expr2)
        if dtype(expr1) is bool:
            if expr2 is False:
                return expr1
            elif expr2 is True:
                return ~expr1
        return self


class LogicalOp(BinaryOp):
    commutative = True

    def dtype(self):
        assert dtype(self.expr1) is bool
        assert dtype(self.expr2) is bool
        return bool

    def op_str(self):
        return self.__class__.__name__.lower()

class And(LogicalOp):
    priority = 7
    neutral_value = True
    overpowering_value = False
    accepted_types = (bool,)

    def simplify(self):
        presimplified = super(And, self).simplify()
        if presimplified is not self:
            return presimplified
        
        # (v >= value) & (v <= value)   ->   (v == value)    
        if isinstance(presimplified, And):
            e1 = presimplified.expr1
            e2 = presimplified.expr2
            if isinstance(e1, GreaterOrEqual) and isinstance(e2, LowerOrEqual):
                if isequal(e1.expr1, e2.expr1) and isequal(e1.expr2, e2.expr2):
                    return e1.expr1 == e1.expr2
        return presimplified

def flatten(expr):
    '''
    converts to a flat list of object that are comparable.
    see numexpr.expressionToAST(ex) for inspiration
    '''
    pass

def unflatten(expr_set, op):
    pass
            
def extract_common_subset(e1, e2):
#    op = e1.__class__
#    if isinstance(e2, op):
#        e1_flat = flatten(e1)
#        e2_flat = flatten(e2)
#        e1set = orderedset(e1_flat)
#        e2set = orderedset(e2_flat)
#        commonset = e1set & e2set
#        common = unflatten(commonset, op)
#        e1_rest = unflatten(e1set - commonset, op)
#        e2_rest = unflatten(e2set - commonset, op)
#        return common, e1_rest, e2_rest
#    else:
#        return None, e1, e2
        
    folded_cond = None
    while isinstance(e1, And) and isinstance(e2, And) and \
          isequal(e1.expr1, e2.expr1):
        if folded_cond is None:
            folded_cond = e1.expr1
        else:
            folded_cond &= e1.expr1
        e1, e2 = e1.expr2, e2.expr2
    return folded_cond, e1, e2
            
class Or(LogicalOp):
    priority = 9
    neutral_value = False
    overpowering_value = True 
    accepted_types = (bool,)

    def simplify(self):
        presimplified = super(Or, self).simplify()
        if presimplified is not self:
            return presimplified
        
        if isinstance(presimplified, Or):
            cs, e1, e2 = extract_common_subset(presimplified.expr1, 
                                               presimplified.expr2)
            if cs is not None:
                return cs & (e1 | e2)
            
            # A or not A -> True                    
            # not A or A -> True                    
            if isinstance(e1, Not) and isequal(e1.expr, e2) or \
               isinstance(e2, Not) and isequal(e2.expr, e1):
                return True
            
        return presimplified

    
class Addition(BinaryOp):
    priority = 5
    commutative = True
    neutral_value = 0.0
    overpowering_value = None 
    accepted_types = (float,)

    def simplify(self):
        if dtype(self.expr1) is bool and dtype(self.expr2) is bool:
            return self.expr1 | self.expr2
        else:
            return super(Addition, self).simplify()

class Substraction(BinaryOp):
    priority = 5
    commutative = False
    neutral_value = 0.0
    overpowering_value = None 
    accepted_types = (float,)
    
class Multiplication(BinaryOp):
    priority = 4
    commutative = True
    neutral_value = 1.0
    overpowering_value = 0.0 
    accepted_types = (float,)

class Division(BinaryOp):
    priority = 4
    commutative = False
    neutral_value = 1.0
    overpowering_value = None
    accepted_types = (float,)


class Variable(Expr):
    def __init__(self, name, dtype):
        self.name = name
        self.value = None
        self._dtype = dtype

    def as_string(self, indent):
        if self.value is None:
            return self.name
        else:
            return str(self.value)
        
    def simplify(self):
        if self.value is None:
            return self
        else:
            return self.value

    def collect_variables(self):
        return set([self.name])

    def dtype(self):
        return self._dtype
    
    def isequal(self, other):
        if isinstance(other, Variable) and self.name == other.name:
            assert self._dtype == other._dtype
            assert self.value == other.value
            return True
        else:
            return False

class SubscriptableVariable(Variable):
    def __init__(self, name):
        self.name = name
        self.value = None
        self._dtype = float

    def __getitem__(self, key):
        return SubscriptedVariable(self.name, key)

class SubscriptedVariable(Variable):
    def __init__(self, name, key):
        Variable.__init__(self, name, float)
        self.key = key
    
    def as_string(self, indent):
        return '%s[%s]' % (self.name, self.key)

    def isequal(self, other):
        isequ = super(SubscriptedVariable, self).isequal(other) and \
               isinstance(other, SubscriptedVariable) and \
               isequal(self.key, other.key)
        return isequ

    
class Function(Expr):
    name = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
    
    def as_string(self, indent):
        args = ', '.join(as_string(arg, indent) for arg in self.args)
        kwargs = ', '.join("%s=%s" % (k, as_string(v, indent))
                           for k, v in self.kwargs.iteritems())
        all_args = "%s%s%s" % (args, ', ', kwargs) if args and kwargs else args
        return "%s(%s)" % (self.name, all_args)

    def isequal(self, other):
        if not isinstance(other, Function):
            return False
        self_kwargs = sorted(self.kwargs.items())
        other_kwargs = sorted(other.kwargs.items())
        kwargs_equal = all(k1 == k2 and isequal(v1, v2)
                           for (k1, v1), (k2, v2)
                           in zip(self_kwargs, other_kwargs))
        args_equal = all(isequal(self_arg, other_arg)
                         for self_arg, other_arg in zip(self.args, other.args))  
        return self.name == other.name and args_equal and kwargs_equal
            
    def simplify(self):
        sargs = [simplify(arg) for arg in self.args]
        skwargs = dict((k, simplify(v)) for k, v in self.kwargs.items())
        if all(sarg is arg for arg, sarg in zip(self.args, sargs)) and \
           all(skwargs[k] is self.kwargs[k] for k in self.kwargs.iterkeys()):
            return self
        return self.__class__(*sargs, **skwargs)
    

    

        
class Where(Function):
    name = 'if'

    def as_string(self, indent):
        arg_indent = indent + '   '
        arg_strings = [as_string(arg, arg_indent) for arg in self.args]
        all_args = (',\n' + arg_indent).join(arg_strings)
        return "%s(%s)" % (self.name, all_args)


    def simplify(self):
        assert len(self.args) == 3
        
        orig_cond, orig_iftrue, orig_iffalse = self.args
        assert dtype(orig_cond) is bool
        
        cond = simplify(orig_cond)
        iftrue, iffalse = simplify(orig_iftrue), simplify(orig_iffalse)
        if cond is not orig_cond or \
           iftrue is not orig_iftrue or \
           iffalse is not orig_iffalse:
            return Where(cond, iftrue, iffalse) 
        
        # This is not really correct (it changes the type of the whole
        # expression) but it seems correct in most cases. Ideally, we should
        # only do this if the type for the enclosing expr (ie the target
        # variable) is boolean.
        if not isinstance(iftrue, Expr) and not isinstance(iffalse, Expr) and \
           iftrue in (False, True) and iffalse in (False, True) and \
           (iftrue is not bool(iftrue) or iffalse is not bool(iffalse)):
            return Where(cond, bool(iftrue), bool(iffalse))

        # type cast
        dtypeiftrue = dtype(iftrue)
        dtypeiffalse = dtype(iffalse)
        if dtypeiftrue is bool and not isinstance(iffalse, Expr) and iffalse in (False, True):
            if iffalse:
                if not isinstance(iffalse, bool):
                    return Where(cond, iftrue, True)
                # optimize if(A, B, True)" to "not A or B"
#                return ~cond | iftrue
            else:
                # optimize "if(A, B, False)" to "A and B"
                return cond & iftrue
            
        if dtypeiffalse is bool and not isinstance(iftrue, Expr) and iftrue in (False, True):
            if iftrue:
                # optimize "if(A, True, B)" to "A or B"
                return cond | iffalse
            else:
                if not isinstance(iftrue, bool):
                    return Where(cond, False, iffalse)
                # optimize "if(A, False, B)" to "not A and B"
#                return ~cond & iffalse

        if iftrue is True and iffalse is False:
            return cond
        if iftrue is False and iffalse is True:
            return ~cond
        
        if cond is True:
            return iftrue
        if cond is False:
            return iffalse
        
        if isequal(iftrue, iffalse):
            return iftrue

#        if iffalse is 0: # this one decrease readability in some cases
#            return cond * iftrue

        if isinstance(iffalse, Where):
            # if(cond1, 
            #    value1, 
            #    if(cond2, 
            #       value1, 
            #       if(cond3, 
            #          value1, 
            #          value2)))
            # ->
            # if(cond1 | cond2 | cond3, value1, value2)
            folded_cond = cond
            other = iffalse
            # while iftrue == other.iftrue
            while isinstance(other, Where):
                other_cond, other_iftrue, other_iffalse = other.args
                if not isequal(other_iftrue, iftrue):
                    break
                folded_cond |= other_cond
                other = other_iffalse

            if folded_cond is not cond:
                return Where(folded_cond, iftrue, other)

            iffalse_cond, iffalse_iftrue, iffalse_iffalse = iffalse.args

            # if(A, B, if(not A, C, D))
            # ->
            # if(A, B, C)
            # if(not A, B, if(A, C, D))
            # ->
            # if(not A, B, C)
            if (isinstance(iffalse_cond, Not) and
                isequal(cond, iffalse_cond.expr)) or \
               (isinstance(cond, Not) and
                isequal(cond.expr, iffalse_cond)):
                return Where(cond, iftrue, iffalse_iftrue)

            # if(A, B, if(A, C, D))
            # ->
            # if(A, B, D)
            if (isequal(cond, iffalse_cond)):
                return Where(cond, iftrue, iffalse_iffalse)

            # if(A & B, C, if(A & not B, E, F))
            # ->
            # if(A, if(B, C, if(D, E, F)), F)
            if not isinstance(iffalse_iffalse, Expr):
                cs, e1, e2 = extract_common_subset(cond, iffalse_cond)
                if cs is not None:
                    return Where(cs, 
                                 Where(e1, 
                                       iftrue, 
                                       Where(e2, 
                                             iffalse_iftrue, 
                                             iffalse_iffalse)),
                                 iffalse_iffalse)

        if isinstance(iftrue, Where):
            # if(cond1,
            #    if(cond2,
            #       if(cond3,
            #          value1,
            #          value2),
            #       value2),
            #    value2)
            # ->
            # if(cond1 & cond2 & cond3, value1, value2)
            folded_cond = cond
            other = iftrue
            # while iftrue == other.iftrue
            while isinstance(other, Where):
                other_cond, other_iftrue, other_iffalse = other.args
                if not isequal(other_iffalse, iffalse):
                    break
                folded_cond &= other_cond
                other = other_iftrue
            if folded_cond is not cond:
                return Where(folded_cond, other, iffalse)

            iftrue_cond, iftrue_iftrue, iftrue_iffalse = iftrue.args
            
            if (isequal(cond, iftrue_cond)):
                # if(A, if(A, B, C), D)
                # ->
                # if(A, B, D)
                return Where(cond, iftrue_iftrue, iffalse)
                
        if isinstance(cond, Not):
            return Where(cond.expr, iffalse, iftrue)

        return self        

    def dtype(self):
        assert dtype(self.args[0]) == bool
        return coerce_types(*self.args[1:])
        

class ZeroClip(Function):
    name = 'zeroclip'

    def simplify(self):
        assert len(self.args) == 3
        expr, minvalue, maxvalue = self.args
        expr = simplify(expr)
        minvalue, maxvalue = simplify(minvalue), simplify(maxvalue)
        if isequal(minvalue, maxvalue):
            return (expr == minvalue) * minvalue
        else:
            return ZeroClip(expr, minvalue, maxvalue)

    def dtype(self):
        return dtype(self.args[0])
        
def makefunc(fname, dtype_=None):
    class Func(Function):
        name = fname
        if dtype_ == 'coerce':
            def dtype(self):
                return coerce_types(*self.args)
        elif dtype_ is not None:
            def dtype(self):
                return dtype_
        else:
            def dtype(self):
                return None 
    Func.__name__ = fname.title()
    return Func

ContRegr = makefunc('cont_regr')
ClipRegr = makefunc('clip_regr')
LogitRegr = makefunc('logit_regr')
LogRegr = makefunc('log_regr')


class LinkValue(Variable):
    def __init__(self, name, key, missing_value):
        Variable.__init__(self, '%s.%s' % (name, key), int)

class Link(object):
    def __init__(self, name, link_field, target_entity):
        # the leading underscores are necessary to not collide with user-defined
        # fields via __getattr__.
        self._name = name
        self._link_field = link_field
        self._target_entity = target_entity

    def get(self, key, missing_value=0.0):
        return LinkValue(self._name, key, missing_value)

    __getattr__ = get

    def __str__(self):
        return self._name
    __repr__ = __str__

functions = {'lag': makefunc('lag', 'coerce'),
             'countlink': makefunc('countlink', int), 
             'sumlink': makefunc('sumlink', float), 
             'duration': makefunc('duration', int), 
             'do_divorce': makefunc('do_divorce', int), 
             'KillPerson': makefunc('kill', int),
             'new': makefunc('new', int),
             'max': makefunc('max', 'coerce'),
             'min': makefunc('min', 'coerce'),
             'round': makefunc('round', float),
             'mean': makefunc('mean', float),
             'where': Where,
             'cont_regr': ContRegr,
             'clip_regr': ClipRegr,
             'logit_regr': LogitRegr,
             'log_regr': LogRegr,
             'zeroclip': ZeroClip}


and_re = re.compile('([ )])and([ (])')
or_re = re.compile('([ )])or([ (])')
not_re = re.compile(r'([ (=]|^)not(?=[ (])')


def parse(s, globals=None, expression=True):
    # this prevents any function named something ending in "if"
    str_to_parse = s.replace('if(', 'where(')
    str_to_parse = and_re.sub(r'\1&\2', str_to_parse)
    str_to_parse = or_re.sub(r'\1|\2', str_to_parse)
    str_to_parse = not_re.sub(r'\1~', str_to_parse)
    str_to_parse = str_to_parse.strip()

    mode = 'eval' if expression else 'exec'
    try:
        c = compile(str_to_parse, '<expr>', mode)
    except SyntaxError:
        print "syntax error in: ", s
        raise

#    varnames = c.co_names
#    variables = [(name, Variable(name)) for name in varnames]
#    context = dict(variables)
#    context.update(functions)

    context = functions.copy()
    if globals is not None:
        context.update(globals)

    context['__builtins__'] = None
    if expression:
        return eval(c, context)
    else:
        exec(c, context)
    
        # cleanup result
        del context['__builtins__']
        for funcname in functions.keys():
            del context[funcname]
        return context
