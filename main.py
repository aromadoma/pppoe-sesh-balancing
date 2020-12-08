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
    bba_group_names = (f'PPPOE_{interface_number}', f'PPPOE_NAT_{interface_number}')

    return bba_group_names


def get_pado_delay(sessions_number, threshold_256, threshold_512, threshold_9999):
    """

    :param sessions_number: number of sessions on interface
    :param threshold_256: int, if number of sessions reaches the threshold, pado delay will be 256
    :param threshold_512: int, if number of sessions reaches the threshold, pado delay will be 512
    :param threshold_9999: int, if number of sessions reaches the threshold, pado delay will be 9999
    :return:
    """
    if sessions_number < threshold_256:
        pado_delay = 0
    elif threshold_256 <= sessions_number < threshold_512:
        pado_delay = 256
    elif threshold_512 <= sessions_number < threshold_9999:
        pado_delay = 512
    else:
        pado_delay = 9999

    return pado_delay


def get_pado_delay_current_dict(ssh_connection):
    """

    :param ssh_connection:
    :return:
    """
    pado_delay_current_dict = {}  # Dictionary for pairs of bba_group_name:pado_delay_current_dict

    for line in ssh_connection.send_command('sh run | sec bba').split(sep='\n'):
        if line.startswith('bba-group pppoe'):
            bba_group_name = re.search(r'bba-group pppoe (\S+)', line).group(1)
            pado_delay_current_dict[bba_group_name] = 0
        elif line.startswith(' pado delay'):
            pado_delay_current = re.search(r'pado delay (\S+)', line).group(1)
            pado_delay_current_dict[bba_group_name] = int(pado_delay_current)

    return pado_delay_current_dict


def is_pado_change_needed(bba_group_name, pado_delay, pado_delay_current_dict):
    """

    :param bba_group_name:
    :param pado_delay:
    :param pado_delay_current_dict:
    :return:
    """
    if bba_group_name in pado_delay_current_dict and pado_delay != pado_delay_current_dict[bba_group_name]:
        return True
    else:
        return False
    

def create_pado_config_set(ssh_connection, interfaces_and_pado_list):
    """

    :param ssh_connection:
    :param interfaces_and_pado_list: list of pair of all BRAS' interfaces and corresponding pado delay values
    :return: list of str, commands for netmiko to send to device
    """
    config_set = []
    pado_delay_current_dict = get_pado_delay_current_dict(ssh_connection)
    for interface_name, pado_delay in interfaces_and_pado_list:
        for bba_group_name in get_bba_group_names(interface_name):

            # Checking if there are diffs between current pado_delay and new calculated pado_delay values:
            if is_pado_change_needed(bba_group_name, pado_delay, pado_delay_current_dict):
                config_set += [f'bba-group pppoe {bba_group_name}', f'pado delay {pado_delay}']

    return config_set


def set_pado_delay(ssh_connection, interfaces_and_pado_list):
    """

    :param interfaces_and_pado_list: list of pair of all BRAS' interfaces and corresponding pado delay values
    :param ssh_connection: connection, established via netmiko
    :return: None
    """

    config_set = create_pado_config_set(ssh_connection, interfaces_and_pado_list)
    if config_set:  # If config_set is not empty
        ssh_connection.send_config_set(config_set)


def main():
    # Path to parameters file:
    parameters_path = os.path.join(os.path.dirname(__file__), 'parameters.json')

    # Loading parameters from parameters.json:
    with open(parameters_path) as parameters_file:
        parameters = json.load(parameters_file)
        ssh_username = parameters['ssh_username']
        ssh_password = parameters['ssh_password']
        threshold_256 = parameters['threshold_256']
        threshold_512 = parameters['threshold_512']
        threshold_9999 = parameters['threshold_9999']
        bras_dict = parameters['bras_dict']

    print(f'{datetime.now()} Starting the pppoe_session_balancing script as {ssh_username}')
    print(
        f'{datetime.now()} Current thresholds are {threshold_256} for 256, {threshold_512} for 512, {threshold_9999} for 9999')

    for device_ip in bras_dict.keys():
        if device_ip.startswith('#'):  # handling comment lines
            continue
        log_message = bras_dict[device_ip] + '>> '
        print(f'{datetime.now()} Connecting to {bras_dict[device_ip]}... ', end='')

        # Connecting to device:
        ssh_connection = connection_to_iosxe(ssh_username, ssh_password, device_ip)
        if ssh_connection is None:  # If a connection failed, skipping this BRAS
            continue

        # Creating a list with pairs of BRAS' interfaces and corresponding pado delay values:
        interfaces_and_pado_list = []

        # Pull current sessions amount on BRAS interfaces:
        for interface_name, sessions_num in get_interfaces_and_sessions(ssh_connection):

            # Calculating pado delay value to be applied to bba-group according to thresholds:
            pado_delay = get_pado_delay(int(sessions_num), threshold_256, threshold_512, threshold_9999)
            log_message += get_interface_number(interface_name) + ': PADO=' + str(pado_delay) + ', '

            # Adding interface-pado info to common list:
            interfaces_and_pado_list.append([interface_name, pado_delay])

        # Send interfaces-pado common list to be applied on BRASes:
        set_pado_delay(ssh_connection, interfaces_and_pado_list)

        print(f'{datetime.now()} {log_message}')


if __name__ == '__main__':
    main()
