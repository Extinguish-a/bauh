import re
from threading import Thread
from typing import List, Set

from bauh.commons.system import run_cmd, new_subprocess, new_root_subprocess, SystemProcess

RE_DEPS = re.compile(r'[\w\-_]+:[\s\w_\-\.]+\s+\[\w+\]')
RE_OPTDEPS = re.compile(r'[\w\._\-]+\s*:')


def is_enabled() -> bool:
    res = run_cmd('which pacman')
    return res and not res.strip().startswith('which ')


def get_mirrors(pkgs: Set[str]) -> dict:
    pkgre = '|'.join(pkgs).replace('+', r'\+').replace('.', r'\.')

    searchres = new_subprocess(['pacman', '-Ss', pkgre]).stdout
    mirrors = {}

    for line in new_subprocess(['grep', '-E', '.+/({}) '.format(pkgre)], stdin=searchres).stdout:
        if line:
            match = line.decode()
            for p in pkgs:
                if p in match:
                    mirrors[p] = match.split('/')[0]

    return mirrors


def is_available_from_mirrors(pkg_name: str) -> bool:
    return bool(run_cmd('pacman -Ss ' + pkg_name))


def get_info(pkg_name) -> str:
    return run_cmd('pacman -Qi ' + pkg_name)


def get_info_list(pkg_name: str) -> List[tuple]:
    info = get_info(pkg_name)
    if info:
        return re.findall(r'(\w+\s?\w+)\s*:\s*(.+(\n\s+.+)*)', info)


def get_info_dict(pkg_name: str) -> dict:
    info_list = get_info_list(pkg_name)

    if info_list:
        info_dict = {}
        for info_data in info_list:
            attr = info_data[0].lower().strip()
            info_dict[attr] = info_data[1]

            if info_dict[attr] == 'None':
                info_dict[attr] = None

            if attr == 'optional deps' and info_dict[attr]:
                info_dict[attr] = info_dict[attr].split('\n')
            elif attr == 'depends on' and info_dict[attr]:
                info_dict[attr] = [d.strip() for d in info_dict[attr].split(' ') if d]

        return info_dict


def list_installed() -> Set[str]:
    return {out.decode().strip() for out in new_subprocess(['pacman', '-Qq']).stdout if out}


def check_installed(pkg: str) -> bool:
    res = run_cmd('pacman -Qq ' + pkg, print_error=False)
    return bool(res)


def _fill_ignored(res: dict):
    res['pkgs'] = list_ignored_packages()


def list_and_map_installed() -> dict:  # returns a dict with with package names as keys and versions as values
    installed = new_subprocess(['pacman', '-Qq']).stdout  # retrieving all installed package names
    allinfo = new_subprocess(['pacman', '-Qi'], stdin=installed).stdout  # retrieving all installed packages info

    ignored = {}
    thread_ignored = Thread(target=_fill_ignored, args=(ignored,))
    thread_ignored.start()

    pkgs, current_pkg = {'mirrors': {}, 'not_signed': {}}, {}
    for out in new_subprocess(['grep', '-E', '(Name|Description|Version|Validated By)'],
                              stdin=allinfo).stdout:  # filtering only the Name and Validated By fields:
        if out:
            line = out.decode()

            if line.startswith('Name'):
                current_pkg['name'] = line.split(':')[1].strip()
            elif line.startswith('Version'):
                version = line.split(':')
                current_pkg['version'] = version[len(version) - 1].strip()
            elif line.startswith('Description'):
                current_pkg['description'] = line.split(':')[1].strip()
            elif line.startswith('Validated'):

                if line.split(':')[1].strip().lower() == 'none':
                    pkgs['not_signed'][current_pkg['name']] = {'version': current_pkg['version'],
                                                               'description': current_pkg['description']}

                current_pkg = {}

    if pkgs and pkgs.get('not_signed'):
        thread_ignored.join()

        if ignored['pkgs']:
            to_del = set()
            for pkg in pkgs['not_signed'].keys():
                if pkg in ignored['pkgs']:
                    to_del.add(pkg)

            for pkg in to_del:
                del pkgs['not_signed'][pkg]

    return pkgs


def install_as_process(pkgpath: str, root_password: str, aur: bool, pkgdir: str = '.') -> SystemProcess:
    if aur:
        cmd = ['pacman', '-U', pkgpath, '--noconfirm']  # pkgpath = install file path
    else:
        cmd = ['pacman', '-S', pkgpath, '--noconfirm']  # pkgpath = pkgname

    return SystemProcess(new_root_subprocess(cmd, root_password, cwd=pkgdir), wrong_error_phrase='warning:')


def list_desktop_entries(pkgnames: Set[str]) -> List[str]:
    if pkgnames:
        installed_files = new_subprocess(['pacman', '-Qlq', *pkgnames])

        desktop_files = []
        for out in new_subprocess(['grep', '-E', ".desktop$"], stdin=installed_files.stdout).stdout:
            if out:
                desktop_files.append(out.decode().strip())

        return desktop_files


def list_icon_paths(pkgnames: Set[str]) -> List[str]:
    installed_files = new_subprocess(['pacman', '-Qlq', *pkgnames])

    icon_files = []
    for out in new_subprocess(['grep', '-E', '.(png|svg|xpm)$'], stdin=installed_files.stdout).stdout:
        if out:
            line = out.decode().strip()
            if line:
                icon_files.append(line)

    return icon_files


def list_bin_paths(pkgnames: Set[str]) -> List[str]:
    installed_files = new_subprocess(['pacman', '-Qlq', *pkgnames])

    bin_paths = []
    for out in new_subprocess(['grep', '-E', '^/usr/bin/.+'], stdin=installed_files.stdout).stdout:
        if out:
            line = out.decode().strip()
            if line:
                bin_paths.append(line)

    return bin_paths


def list_installed_files(pkgname: str) -> List[str]:
    installed_files = new_subprocess(['pacman', '-Qlq', pkgname])

    f_paths = []

    for out in new_subprocess(['grep', '-E', '/.+\..+[^/]$'], stdin=installed_files.stdout).stdout:
        if out:
            line = out.decode().strip()
            if line:
                f_paths.append(line)

    return f_paths


def verify_pgp_key(key: str) -> bool:
    list_key = new_subprocess(['pacman-key', '-l']).stdout

    for out in new_subprocess(['grep', " " + key], stdin=list_key).stdout:
        if out:
            line = out.decode().strip()
            if line and key in line:
                return True

    return False


def receive_key(key: str, root_password: str) -> SystemProcess:
    return SystemProcess(new_root_subprocess(['pacman-key', '-r', key], root_password=root_password), check_error_output=False)


def sign_key(key: str, root_password: str) -> SystemProcess:
    return SystemProcess(new_root_subprocess(['pacman-key', '--lsign-key', key], root_password=root_password), check_error_output=False)


def list_ignored_packages(config_path: str = '/etc/pacman.conf') -> Set[str]:
    pacman_conf = new_subprocess(['cat', config_path])

    ignored = set()
    grep = new_subprocess(['grep', '-Eo', r'\s*#*\s*ignorepkg\s*=\s*.+'], stdin=pacman_conf.stdout)
    for o in grep.stdout:
        if o:
            line = o.decode().strip()

            if not line.startswith('#'):
                ignored.add(line.split('=')[1].strip())

    pacman_conf.terminate()
    grep.terminate()
    return ignored