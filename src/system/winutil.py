"""Windows-specific helpers: Win32/ctypes calls, registry lookups, VDF parsing.

Pure functions with no GUI dependencies. Used by core (foreground window check,
steam nick) and gui (admin / -condebug startup warnings).
"""
import logging
import os
import winreg
from ctypes import wintypes, windll, create_unicode_buffer, byref, POINTER, sizeof

import vdf

logger = logging.getLogger(__name__)

windll.advapi32.OpenProcessToken.restype = wintypes.BOOL
windll.advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, POINTER(wintypes.HANDLE)]

windll.advapi32.GetTokenInformation.restype = wintypes.BOOL
windll.advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, POINTER(None), wintypes.DWORD,
                                                POINTER(wintypes.DWORD)]

windll.kernel32.CloseHandle.restype = wintypes.BOOL
windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

windll.kernel32.FormatMessageW.restype = wintypes.DWORD
windll.kernel32.FormatMessageW.argtypes = [wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD, wintypes.DWORD,
                                           POINTER(wintypes.LPWSTR), wintypes.DWORD, wintypes.LPVOID]

windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
windll.kernel32.GetCurrentProcess.argtypes = []

windll.kernel32.GetLastError.restype = wintypes.DWORD
windll.kernel32.GetLastError.argtypes = []

windll.kernel32.LocalFree.restype = wintypes.HLOCAL
windll.kernel32.LocalFree.argtypes = [wintypes.HLOCAL]

FORMAT_MESSAGE_ALLOCATE_BUFFER = 0x100
FORMAT_MESSAGE_FROM_SYSTEM = 0x1000
FORMAT_MESSAGE_IGNORE_INSERTS = 0x200

TOKEN_READ = 0x20008  # STANDARD_RIGHTS_READ | TOKEN_QUERY
TokenElevationType = 18  # TOKEN_INFORMATION_CLASS.TokenElevationType
TokenElevation = 20  # TOKEN_INFORMATION_CLASS.TokenElevation
TokenElevationTypeLimited = 3  # TOKEN_ELEVATION_TYPE.TokenElevationTypeLimited


def log_last_win_error(user_data=None):
    err = windll.kernel32.GetLastError()

    buf = wintypes.LPWSTR(0)
    default_lang_id = wintypes.DWORD(1024)  # MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT)

    res = windll.kernel32.FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                                         FORMAT_MESSAGE_IGNORE_INSERTS, 0, err, default_lang_id, byref(buf), 0, 0)

    if user_data:
        logger.error(f"{user_data} - Win Error [{err}] - {buf.value}")
    else:
        logger.error(f"Win Error [{err}] - {buf.value}")

    if res != 0:
        windll.kernel32.LocalFree(buf)


def is_running_as_admin():
    token_handle = wintypes.HANDLE()
    if not windll.advapi32.OpenProcessToken(windll.kernel32.GetCurrentProcess(), TOKEN_READ, byref(token_handle)):
        log_last_win_error('OpenProcessToken')
        return False

    token_information_elevation_type = wintypes.DWORD(0)
    buf_len = wintypes.DWORD(0)
    if (not windll.advapi32.GetTokenInformation(token_handle, TokenElevationType,
                                                byref(token_information_elevation_type),
                                                sizeof(token_information_elevation_type), byref(buf_len))
            or sizeof(token_information_elevation_type) != buf_len.value):
        windll.kernel32.CloseHandle(token_handle)
        log_last_win_error('GetTokenInformation')
        return False

    logger.debug(f"Token elevation type: {token_information_elevation_type.value}")

    token_information_elevation = wintypes.DWORD(0)
    buf_len = wintypes.DWORD(0)
    if (not windll.advapi32.GetTokenInformation(token_handle, TokenElevation, byref(token_information_elevation),
                                                sizeof(token_information_elevation), byref(buf_len))
            or sizeof(token_information_elevation) != buf_len.value):
        windll.kernel32.CloseHandle(token_handle)
        log_last_win_error('GetTokenInformation')
        return False

    logger.debug(f"Token elevation: {token_information_elevation.value}")

    windll.kernel32.CloseHandle(token_handle)
    return (token_information_elevation_type.value != TokenElevationTypeLimited
            and token_information_elevation.value != 0)


def get_steam_path():
    reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Wow6432Node\\Valve\\Steam')
    path = winreg.QueryValueEx(reg_key, 'InstallPath')[0]
    winreg.CloseKey(reg_key)
    return str(path)


def get_cs_path():
    reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\Valve\\cs2')
    path = winreg.QueryValueEx(reg_key, 'installpath')[0]
    winreg.CloseKey(reg_key)
    return str(path)


def get_active_steam_id():
    reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Valve\\Steam\\ActiveProcess')
    steam_id = winreg.QueryValueEx(reg_key, 'ActiveUser')[0]
    winreg.CloseKey(reg_key)
    return steam_id


def get_last_steam_nick():
    reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Valve\\Steam')
    name = winreg.QueryValueEx(reg_key, 'LastGameNameUsed')[0]
    winreg.CloseKey(reg_key)
    return name


def is_condebug_in_game_args():
    steam_path = get_steam_path()
    if not steam_path:
        logger.warning('Could not get Steam path')
        return False

    user_id = get_active_steam_id()
    if user_id == 0:
        logger.warning('Could not identify active Steam user (is Steam running?)')
        return False

    cfg_path = os.path.join(steam_path, 'userdata', str(user_id), 'config', 'localconfig.vdf')
    if not os.path.exists(cfg_path):
        logger.warning('Steam missing localconfig.vdf')
        return False

    try:
        cfg = vdf.load(open(cfg_path, encoding='utf-8'))

        if 'Steam' in cfg['UserLocalConfigStore']['Software']['Valve']:
            args = cfg['UserLocalConfigStore']['Software']['Valve']['Steam']['apps']['730']['LaunchOptions']
        else:
            args = cfg['UserLocalConfigStore']['Software']['Valve']['steam']['apps']['730']['LaunchOptions']

        return '-condebug' in args.lower()
    except:
        return False


def get_foreground_window_title():
    window_handle = windll.user32.GetForegroundWindow()
    length = windll.user32.GetWindowTextLengthW(window_handle)
    buf = create_unicode_buffer(length + 2)
    windll.user32.GetWindowTextW(window_handle, buf, length + 2)
    return buf.value
