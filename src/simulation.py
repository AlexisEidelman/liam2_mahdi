from __future__ import print_function, division

import time
import os.path
import operator
from collections import defaultdict
import random
import warnings

import numpy as np
import tables
import yaml

from context import EvaluationContext
from data import H5Data, Void
from entities import Entity, global_symbols
from utils import (time2str, timed, gettime, validate_dict,
                   expand_wild, multi_get, multi_set,
                   merge_dicts, merge_items,
                   field_str_to_type, fields_yaml_to_type)
import config
import console
import expr


def show_top_times(what, times, count):
    """
    >>> show_top_times("letters", [('a', 0.1), ('b', 0.2)], 5)
    top 5 letters:
     - a: 0.10 second (33%)
     - b: 0.20 second (66%)
    total for top 5 letters: 0.30 second
    >>> show_top_times("zeros", [('a', 0)], 5)
    top 5 zeros:
     - a: 0 ms (100%)
    total for top 5 zeros: 0 ms
    """
    total = sum(t for n, t in times)
    print("top %d %s:" % (count, what))
    for name, timing in times[:count]:
        try:
            percent = 100.0 * timing / total
        except ZeroDivisionError:
            percent = 100
        print(" - %s: %s (%d%%)" % (name, time2str(timing), percent))
    print("total for top %d %s:" % (count, what), end=' ')
    print(time2str(sum(timing for name, timing in times[:count])))


def show_top_processes(process_time, count):
    process_times = sorted(process_time.iteritems(),
                           key=operator.itemgetter(1),
                           reverse=True)
    show_top_times('processes', process_times, count)


def show_top_expr(count=None):
    show_top_times('expressions', expr.timings.most_common(count), count)


def expand_periodic_fields(content):
    periodic = multi_get(content, 'globals/periodic')
    if isinstance(periodic, list) and \
            all(isinstance(f, dict) for f in periodic):
        multi_set(content, 'globals/periodic', {'fields': periodic})


def handle_imports(content, directory):
    import_files = content.get('import', [])
    if isinstance(import_files, basestring):
        import_files = [import_files]
    for fname in import_files[::-1]:
        import_path = os.path.join(directory, fname)
        print("importing: '%s'" % import_path)
        import_directory = os.path.dirname(import_path)
        with open(import_path) as f:
            import_content = handle_imports(yaml.load(f), import_directory)
            expand_periodic_fields(import_content)
            for wild_key in ('globals/*/fields', 'entities/*/fields'):
                multi_keys = expand_wild(wild_key, import_content)
                for multi_key in multi_keys:
                    import_fields = multi_get(import_content, multi_key)
                    local_fields = multi_get(content, multi_key, [])
                    # fields are in "yaml ordered dict" format and we want
                    # simple list of items
                    import_fields = [d.items()[0] for d in import_fields]
                    local_fields = [d.items()[0] for d in local_fields]
                    # merge the lists
                    merged_fields = merge_items(import_fields, local_fields)
                    # convert them back to "yaml ordered dict"
                    merged_fields = [{k: v} for k, v in merged_fields]
                    multi_set(content, multi_key, merged_fields)
            content = merge_dicts(import_content, content)
    return content


class Simulation(object):
    yaml_layout = {
        'import': None,
        'globals': {
            'periodic': None,  # either full-blown (dict) description or list
                               # of fields
            '*': {
                'path': str,
                'type': str,
                'fields': [{
                    '*': None  # Or(str, {'type': str, 'initialdata': bool})
                }],
                'oldnames': {
                    '*': str
                },
                'newnames': {
                    '*': str
                },
                'invert': [str],
                'transposed': bool
            }
        },
        '#entities': {
            '*': {
                'fields': [{
                    '*': None
                }],
                'links': {
                    '*': {
                        '#type': str,  # Or('many2one', 'one2many')
                        '#target': str,
                        '#field': str
                    }
                },
                'macros': {
                    '*': None
                },
                'processes': {
                    '*': None
                }
            }
        },
        '#simulation': {
            'init': [{
                '*': [str]
            }],
            '#processes': [{
                '*': [None]  # Or(str, [str, int])
            }],
            'random_seed': int,
            '#input': {
                'path': str,
                '#file': str,
                'method': str
            },
            '#output': {
                'path': str,
                '#file': str
            },
            'logging': {
                'timings': bool,
                'level': str,  # Or('periods', 'procedures', 'processes')
            },
            '#periods': int,
            '#start_period': int,
            'skip_shows': bool,
            'timings': bool,      # deprecated
            'assertions': str,
            'default_entity': str,
            'autodump': None,
            'autodiff': None,
        }
    }

    def __init__(self, globals_def, periods, start_period, init_processes,
                 processes, entities, data_source, default_entity=None):
        #FIXME: what if period has been declared explicitly?
        if 'periodic' in globals_def:
            globals_def['periodic']['fields'].insert(0, ('PERIOD', int))

        self.globals_def = globals_def
        self.periods = periods
        self.start_period = start_period
        # init_processes is a list of tuple: (process, 1)
        self.init_processes = init_processes
        # processes is a list of tuple: (process, periodicity)
        self.processes = processes
        self.entities = entities
        self.data_source = data_source
        self.default_entity = default_entity

        self.stepbystep = False

    @classmethod
    def from_yaml(cls, fpath,
                  input_dir=None, input_file=None,
                  output_dir=None, output_file=None):
        simulation_path = os.path.abspath(fpath)
        simulation_dir = os.path.dirname(simulation_path)
        with open(fpath) as f:
            content = yaml.load(f)

        expand_periodic_fields(content)
        content = handle_imports(content, simulation_dir)
        validate_dict(content, cls.yaml_layout)

        # the goal is to get something like:
        # globals_def = {'periodic': [('a': int), ...],
        #                'MIG': int}
        globals_def = content.get('globals', {})
        for k, v in content.get('globals', {}).iteritems():
            if "type" in v:
                v["type"] = field_str_to_type(v["type"], "array '%s'" % k)
            else:
                #TODO: fields should be optional (would use all the fields
                # provided in the file)
                v["fields"] = fields_yaml_to_type(v["fields"])
            globals_def[k] = v

        simulation_def = content['simulation']
        seed = simulation_def.get('random_seed')
        if seed is not None:
            seed = int(seed)
            print("using fixed random seed: %d" % seed)
            random.seed(seed)
            np.random.seed(seed)

        periods = simulation_def['periods']
        start_period = simulation_def['start_period']
        config.skip_shows = simulation_def.get('skip_shows', config.skip_shows)
        #TODO: check that the value is one of "raise", "skip", "warn"
        config.assertions = simulation_def.get('assertions', config.assertions)

        logging_def = simulation_def.get('logging', {})
        config.log_level = logging_def.get('level', config.log_level)
        if 'timings' in simulation_def:
            warnings.warn("simulation.timings is deprecated, please use "
                          "simulation.logging.timings instead",
                          DeprecationWarning)
            config.show_timings = simulation_def['timings']
        config.show_timings = logging_def.get('timings', config.show_timings)

        autodump = simulation_def.get('autodump', None)
        if autodump is True:
            autodump = 'autodump.h5'
        if isinstance(autodump, basestring):
            # by default autodump will dump all rows
            autodump = (autodump, None)
        config.autodump = autodump

        autodiff = simulation_def.get('autodiff', None)
        if autodiff is True:
            autodiff = 'autodump.h5'
        if isinstance(autodiff, basestring):
            # by default autodiff will compare all rows
            autodiff = (autodiff, None)
        config.autodiff = autodiff

        input_def = simulation_def['input']
        input_directory = input_dir if input_dir is not None \
                                    else input_def.get('path', '')
        if not os.path.isabs(input_directory):
            input_directory = os.path.join(simulation_dir, input_directory)
        config.input_directory = input_directory

        output_def = simulation_def['output']
        output_directory = output_dir if output_dir is not None \
                                      else output_def.get('path', '')
        if not os.path.isabs(output_directory):
            output_directory = os.path.join(simulation_dir, output_directory)
        if not os.path.exists(output_directory):
            print("creating directory: '%s'" % output_directory)
            os.makedirs(output_directory)
        config.output_directory = output_directory

        if output_file is None:
            output_file = output_def['file']
        output_path = os.path.join(output_directory, output_file)

        entities = {}
        for k, v in content['entities'].iteritems():
            entities[k] = Entity.from_yaml(k, v)

        for entity in entities.itervalues():
            entity.attach_and_resolve_links(entities)

        global_context = {'__globals__': global_symbols(globals_def),
                          '__entities__': entities}
        parsing_context = global_context.copy()
        parsing_context.update((entity.name, entity.all_symbols(global_context))
                               for entity in entities.itervalues())
        for entity in entities.itervalues():
            parsing_context['__entity__'] = entity.name
            entity.parse_processes(parsing_context)
            entity.compute_lagged_fields()
            # entity.optimize_processes()

        # for entity in entities.itervalues():
        #     entity.resolve_method_calls()
        used_entities = set()
        init_def = [d.items()[0] for d in simulation_def.get('init', {})]
        init_processes = []
        for ent_name, proc_names in init_def:
            if ent_name not in entities:
                raise Exception("Entity '%s' not found" % ent_name)

            entity = entities[ent_name]
            used_entities.add(ent_name)
            init_processes.extend([(entity.processes[proc_name], 1)
                                   for proc_name in proc_names])

        processes_def = [d.items()[0] for d in simulation_def['processes']]
        processes = []
        for ent_name, proc_defs in processes_def:
            entity = entities[ent_name]
            used_entities.add(ent_name)
            for proc_def in proc_defs:
                # proc_def is simply a process name
                if isinstance(proc_def, basestring):
                    # use the default periodicity of 1
                    proc_name, periodicity = proc_def, 1
                else:
                    proc_name, periodicity = proc_def
                processes.append((entity.processes[proc_name], periodicity))

        entities_list = sorted(entities.values(), key=lambda e: e.name)
        declared_entities = set(e.name for e in entities_list)
        unused_entities = declared_entities - used_entities
        if unused_entities:
            suffix = 'y' if len(unused_entities) == 1 else 'ies'
            print("WARNING: entit%s without any executed process:" % suffix,
                  ','.join(sorted(unused_entities)))

        method = input_def.get('method', 'h5')

        if method == 'h5':
            if input_file is None:
                input_file = input_def['file']
            input_path = os.path.join(input_directory, input_file)
            data_source = H5Data(input_path, output_path)
        elif method == 'void':
            data_source = Void(output_path)
        else:
            raise ValueError("'%s' is an invalid value for 'method'. It should "
                             "be either 'h5' or 'void'")

        default_entity = simulation_def.get('default_entity')
        return Simulation(globals_def, periods, start_period, init_processes,
                          processes, entities_list, data_source, default_entity)

    def load(self):
        return timed(self.data_source.load, self.globals_def, self.entities_map)

    @property
    def entities_map(self):
        return {entity.name: entity for entity in self.entities}

    def run(self, run_console=False):
        start_time = time.time()
        h5in, h5out, globals_data = timed(self.data_source.run,
                                          self.globals_def,
                                          self.entities_map,
                                          self.start_period - 1)

        if config.autodump or config.autodiff:
            if config.autodump:
                fname, _ = config.autodump
                mode = 'w'
            else:  # config.autodiff
                fname, _ = config.autodiff
                mode = 'r'
            fpath = os.path.join(config.output_directory, fname)
            h5_autodump = tables.open_file(fpath, mode=mode)
            config.autodump_file = h5_autodump
        else:
            h5_autodump = None

#        input_dataset = self.data_source.run(self.globals_def,
#                                             entity_registry)
#        output_dataset = self.data_sink.prepare(self.globals_def,
#                                                entity_registry)
#        output_dataset.copy(input_dataset, self.start_period - 1)
#        for entity in input_dataset:
#            indexed_array = build_period_array(entity)

        # tell numpy we do not want warnings for x/0 and 0/0
        np.seterr(divide='ignore', invalid='ignore')

        process_time = defaultdict(float)
        period_objects = {}
        eval_ctx = EvaluationContext(self, self.entities_map, globals_data)

        def simulate_period(period_idx, period, processes, entities,
                            init=False):
            period_start_time = time.time()

            # set current period
            eval_ctx.period = period

            if config.log_level in ("procedures", "processes"):
                print()
            print("period", period,
                  end=" " if config.log_level == "periods" else "\n")
            if init and config.log_level in ("procedures", "processes"):
                for entity in entities:
                    print("  * %s: %d individuals" % (entity.name,
                                                      len(entity.array)))
            else:
                if config.log_level in ("procedures", "processes"):
                    print("- loading input data")
                    for entity in entities:
                        print("  *", entity.name, "...", end=' ')
                        timed(entity.load_period_data, period)
                        print("    -> %d individuals" % len(entity.array))
                else:
                    for entity in entities:
                        entity.load_period_data(period)
            for entity in entities:
                entity.array_period = period
                entity.array['period'] = period

            if processes:
                num_processes = len(processes)
                for p_num, process_def in enumerate(processes, start=1):
                    process, periodicity = process_def

                    # set current entity
                    eval_ctx.entity_name = process.entity.name

                    if config.log_level in ("procedures", "processes"):
                        print("- %d/%d" % (p_num, num_processes), process.name,
                              end=' ')
                        print("...", end=' ')
                    if period_idx % periodicity == 0:
                        elapsed, _ = gettime(process.run_guarded, eval_ctx)
                    else:
                        elapsed = 0
                        if config.log_level in ("procedures", "processes"):
                            print("skipped (periodicity)")

                    process_time[process.name] += elapsed
                    if config.log_level in ("procedures", "processes"):
                        if config.show_timings:
                            print("done (%s elapsed)." % time2str(elapsed))
                        else:
                            print("done.")
                    self.start_console(eval_ctx)

            if config.log_level in ("procedures", "processes"):
                print("- storing period data")
                for entity in entities:
                    print("  *", entity.name, "...", end=' ')
                    timed(entity.store_period_data, period)
                    print("    -> %d individuals" % len(entity.array))
            else:
                for entity in entities:
                    entity.store_period_data(period)
#            print " - compressing period data"
#            for entity in entities:
#                print "  *", entity.name, "...",
#                for level in range(1, 10, 2):
#                    print "   %d:" % level,
#                    timed(entity.compress_period_data, level)
            period_objects[period] = sum(len(entity.array)
                                         for entity in entities)
            period_elapsed_time = time.time() - period_start_time
            if config.log_level in ("procedures", "processes"):
                print("period %d" % period, end=' ')
            print("done", end=' ')
            if config.show_timings:
                print("(%s elapsed)" % time2str(period_elapsed_time), end="")
                if init:
                    print(".")
                else:
                    main_elapsed_time = time.time() - main_start_time
                    periods_done = period_idx + 1
                    remaining_periods = self.periods - periods_done
                    avg_time = main_elapsed_time / periods_done
                    # future_time = period_elapsed_time * 0.4 + avg_time * 0.6
                    remaining_time = avg_time * remaining_periods
                    print(" - estimated remaining time: %s."
                          % time2str(remaining_time))
            else:
                print()

        print("""
=====================
 starting simulation
=====================""")
        try:
            simulate_period(0, self.start_period - 1, self.init_processes,
                            self.entities, init=True)
            main_start_time = time.time()
            periods = range(self.start_period,
                            self.start_period + self.periods)
            for period_idx, period in enumerate(periods):
                simulate_period(period_idx, period,
                                self.processes, self.entities)

            total_objects = sum(period_objects[period] for period in periods)
            total_time = time.time() - main_start_time
            try:
                ind_per_sec = str(int(total_objects / total_time))
            except ZeroDivisionError:
                ind_per_sec = 'inf'

            print("""
==========================================
 simulation done
==========================================
 * %s elapsed
 * %d individuals on average
 * %s individuals/s/period on average
==========================================
""" % (time2str(time.time() - start_time),
       total_objects / self.periods,
       ind_per_sec))

            show_top_processes(process_time, 10)
#            if config.debug:
#                show_top_expr()

            if run_console:
                console_ctx = eval_ctx.clone(entity_name=self.default_entity)
                c = console.Console(console_ctx)
                c.run()

        finally:
            if h5in is not None:
                h5in.close()
            h5out.close()
            if h5_autodump is not None:
                h5_autodump.close()

    def start_console(self, context):
        if self.stepbystep:
            c = console.Console(context)
            res = c.run(debugger=True)
            self.stepbystep = res == "step"
