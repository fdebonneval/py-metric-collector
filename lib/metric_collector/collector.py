import logging
import requests
import time
from metric_collector import netconf_collector
from metric_collector import f5_rest_collector

logger = logging.getLogger('collector')
global_measurement_prefix = 'metric_collector'

class Collector:

    def __init__(self, hosts_manager, parser_manager):
        self.hosts_manager = hosts_manager
        self.parser_manager = parser_manager

    def collect(self, worker_name, hosts=None, host_cmds=None, cmd_tags=None, dump_queue=None):
        if not hosts and not host_cmds:
            logger.error('Collector: Nothing to collect')
            if dump_queue:
                dump_queue.put([])
            return []
        if hosts:
            host_cmds = {}
            tags = cmd_tags or ['.*']
            for host in hosts:
                cmds = self.hosts_manager.get_target_commands(host, tags=tags) 
                target_cmds = []
                for c in cmds:
                    target_cmds += c['commands']
                host_cmds[host] = target_cmds
               
        values = []
        for host, target_commands in host_cmds.items():
            credential = self.hosts_manager.get_credentials(host)

            host_reacheable = False

            logger.info('Collector starting for: %s', host)
            host_address = self.hosts_manager.get_address(host)
            device_type = self.hosts_manager.get_device_type(host)

            if device_type == 'juniper':
                dev = netconf_collector.NetconfCollector(
                        host=host, address=host_address, credential=credential, parsers=self.parser_manager)
            elif device_type == 'f5':
                dev = f5_rest_collector.F5Collector(
                    host=host, address=host_address, credential=credential, parsers=self.parser_manager)
            dev.connect()

            if dev.is_connected():
                dev.collect_facts()
                host_reacheable = True

            else:
                logger.error('Unable to connect to %s, skipping', host)
                host_reacheable = False

            time_execution = 0
            cmd_successful = 0
            cmd_error = 0

            if host_reacheable:
                time_start = time.time()

                ### Execute commands on the device
                for command in target_commands:
                    try:
                        logger.info('[%s] Collecting > %s' % (host,command))
                        values += dev.collect(command)
                        cmd_successful += 1

                    except Exception as err:
                        cmd_error += 1
                        logger.error('An issue happened while collecting %s on %s > %s ' % (host,command, err))
                        logger.error(traceback.format_exc())

                ### Save collector statistics
                time_end = time.time()
                time_execution = time_end - time_start

            exec_time_datapoint = [{
                'measurement': global_measurement_prefix + '_collector_stats',
                'tags': {
                    'device': dev.hostname,
                    'worker_name': worker_name
                },
                'fields': {
                    'execution_time_sec': "%.4f" % time_execution,
                    'nbr_commands':  cmd_successful + cmd_error,
                    'nbr_successful_commands':  cmd_successful,
                    'nbr_error_commands':  cmd_error,
                    'reacheable': int(host_reacheable),
                    'unreacheable': int(not host_reacheable)
                }
            }]

            values += exec_time_datapoint

            ### if context information are provided add these in the tag list
            ### the context is a list of dict, go over all element and
            ### check if a similar tag already exist
            host_context = self.hosts_manager.get_context(host)
            for value in values:
                for item in host_context:
                    for k, v in item.items():
                        if k in value['tags']:
                            continue
                        value['tags'][k] = v

        if dump_queue:
            dump_queue.put(values)

        return values