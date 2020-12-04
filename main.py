from netmiko.ssh_exception import AuthenticationException, NetMikoTimeoutException
from netmiko import ConnectHandler
import re
from datetime import datetime
import os.path
import json


def connection_to_iosxe(ssh_username, ssh_password, device_ip):
    connection_settings = {
        'device_type': 'cisco_xe',
        'ip': device_ip,
        'username': ssh_username,
        'password': ssh_password,
    }

    i = 0

    while i < 3:  # 3 tries to connect
        try:
            ssh_connection = ConnectHandler(**connection_settings)
        except AuthenticationException:
            print(r'Wrong username\password.')
            i += 1
        except NetMikoTimeoutException:
            print(f'{device_ip} is unreachable. Trying again...')
            i += 1
        else:
            print('Successfully authenticated.')
            return ssh_connection

    print(f'Cannot connect to {device_ip}. Skipping')
    return None


def get_interfaces_and_sessions(ssh_connection):
    """

    :param ssh_connection: ssh_connection, established via netmiko
    :return: list of tuples, which contain interface name and sessions number values
    """

    return re.findall(r'(\S+\d/\d/\d)\s+(\d+)', ssh_connection.send_command('show pppoe summary'))


def get_interface_number(interface_name):
    """

    :param interface_name: str, name of physical interface
    :return: str, number of interface (such as 0/0/1)
    """

    interface_number = re.search(r'\S+(\d/\d/\d)', interface_name).group(1)

    return interface_number


def get_bba_group_names(interface_name):
    """

    :param interface_name: str, name of physical interface
    :return: list, two bba-groups names
    """
    interface_number = get_interface_number(interface_name)
    bba_group_names = (f'PPPOE_{interface_number}', f'PPPoE_NAT_{interface_number}')

    return bba_group_names


def set_pado_delay(ssh_connection, interface_name, pado_delay):
    """

    :param ssh_connection: ssh_connection, established via netmiko
    :param interface_name: str, name of physical interface
    :param pado_delay: int, pado-delay value
    :return: None
    """
    bba_group_names = get_bba_group_names(interface_name)

    # ssh_connection.send_config_set([f'bba-group pppoe {bba_group_names[0]}', f'pado delay {pado_delay}',
    #                                 f'bba-group pppoe {bba_group_names[1]}', f'pado delay {pado_delay}'])

    # print('CONFIGURATION:')
    # print(f'bba-group pppoe {bba_group_names[0]}\n', f'pado delay {pado_delay}\n',
    #       f'bba-group pppoe {bba_group_names[1]}\n', f'pado delay {pado_delay}')

    return None


def main():
    # Path to parameters file:
    parameters_path = os.path.join(os.path.dirname(__file__), 'parameters.json')

    with open(parameters_path) as parameters_file:
        parameters = json.load(parameters_file)
        ssh_username = parameters['ssh_username']
        ssh_password = parameters['ssh_password']
        threshold_256 = parameters['threshold_256']
        threshold_512 = parameters['threshold_512']
        bras_dict = parameters['bras_dict']

    print(f'{datetime.now()} Starting the pppoe_session_balancing script as {ssh_username}')
    print(f'{datetime.now()} Current thresholds are {threshold_256} for 256, {threshold_512} for 512.')

    for device_ip in bras_dict.keys():
        if device_ip.startswith('#'):  # handling comment lines
            continue
        log_message = bras_dict[device_ip] + '>> '
        print(f'{datetime.now()} Connecting to {bras_dict[device_ip]}... ', end='')

        ssh_connection = connection_to_iosxe(ssh_username, ssh_password, device_ip)

        if ssh_connection is None:  # If a connection failed, skipping this BRAS
            continue
        for interface_and_sessions in get_interfaces_and_sessions(ssh_connection):
            interface_name = interface_and_sessions[0]
            sessions_number = int(interface_and_sessions[1])
            if sessions_number < threshold_256:
                pado_delay = 0
            elif threshold_256 <= sessions_number < threshold_512:
                pado_delay = 256
            else:
                pado_delay = 512

            set_pado_delay(ssh_connection, interface_name, pado_delay)
            log_message += get_interface_number(interface_name) + ': PADO=' + str(pado_delay) + ', '

        print(f'{datetime.now()} {log_message}')


if __name__ == '__main__':
    main()
