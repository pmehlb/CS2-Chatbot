"""Top-level NiceGUI shell: the splitter, the tab bar (one tab per area), the
power toggle and the exec-status light.

Activation model: the open tab's area becomes the active area, except for
non-answerable utility areas (Settings), which set active_area to None so the
chat loop idles. Each area renders its own tab body via build_tab.
"""
import logging

from nicegui import ui

from system import winutil
from ui.ui_util import ToggleButton, notify_and_log

logger = logging.getLogger(__name__)


def build(app):
    saved = app.load_app_settings()
    app.response_delay_ms = saved.get('response_delay_ms', app.response_delay_ms)
    app.response_jitter_ms = saved.get('response_jitter_ms', app.response_jitter_ms)
    app.auto_press = saved.get('auto_press', app.auto_press)
    app.cooldown_enabled = saved.get('cooldown_enabled', app.cooldown_enabled)
    app.cooldown_ms = saved.get('cooldown_ms', app.cooldown_ms)
    app.toggle_key = saved.get('toggle_key', app.toggle_key)

    theme = ui.dark_mode()
    theme.enable() if saved.get('dark_theme', True) else theme.disable()
    app.theme = theme  # the Settings area toggles this via app.theme

    ui.query('.nicegui-content').classes('p-0')
    ui.colors(primary=saved.get('primary_color', '#ec4899'))

    # Strip the default paragraph margins from area_header descriptions so the
    # heading block stays compact (scoped to .area-desc, not help dialogs etc.).
    ui.add_css('.area-desc p { margin: 0; }')

    name_to_area = {area.label: area for area in app.areas}
    first = app.areas[0] if app.areas else None
    app.active_area = first if first and first.answerable else None

    def on_tab_change(e):
        # Chat tab -> that area; a non-answerable tab (Settings) -> None -> idle.
        area = name_to_area.get(e.value)
        app.active_area = area if area and area.answerable else None
        logger.debug(f"Active area -> {app.active_area.key if app.active_area else None}")

    with ui.splitter(value=16).classes('w-full h-screen').props(':limits="[16, 32]"') as splitter:
        with splitter.before:
            ui.icon('chat', color='primary').classes('m-auto text-5xl mt-6')

            with ui.tabs(on_change=on_tab_change).props('vertical').classes('w-full h-full') as tabs:
                tab_objs = {area.label: ui.tab(area.label, icon=area.icon) for area in app.areas}

            with ui.row().classes('p-2 mx-auto items-center'):
                toggle_active = ToggleButton(icon='power_settings_new').classes('w-11 animate-pulse')
                with toggle_active:
                    status_badge = ui.badge('OFF').props('floating').classes('bg-red rounded')

                exec_light = ui.icon('circle').classes('text-2xl').props('color=red')
                with exec_light:
                    ui.tooltip('Exec status: green when a reply has been written '
                               'to message.cfg, red while processing.')

        with splitter.after:
            initial_tab = tab_objs[app.areas[0].label] if app.areas else None
            with ui.tab_panels(tabs, value=initial_tab).props('vertical').classes('w-full h-full'):
                for area in app.areas:
                    with ui.tab_panel(tab_objs[area.label]).classes('overflow-x-hidden'):
                        area.build_tab(app)

    toggle_active.on_toggle = lambda new_state: _gate_power(app, new_state, status_badge)

    def set_exec_light(ready):
        exec_light.props(f'color={"green" if ready else "red"}')

    app.exec_state_cb = set_exec_light

    # Global toggle hotkey. The keyboard library fires request_toggle on its own
    # thread, so it only flips a flag; poll_toggle (on the UI thread) clears it
    # and drives the exact same path as clicking the power button.
    def request_toggle():
        app.toggle_requested = True

    app.hotkeys.bind_callback(request_toggle)
    app.hotkeys.rebind(app.toggle_key)  # register the saved key (no-op if unset)

    def poll_toggle():
        if app.toggle_requested:
            app.toggle_requested = False
            toggle_active._handle_click()

    ui.timer(0.1, poll_toggle)


def _gate_power(app, new_state, status_badge):
    """Decide whether the bot may switch on. Returns the state to settle on."""
    if not new_state:
        app.powered_on = False
        status_badge.set_visibility(True)
        notify_and_log('Chatbot has been disabled.', type='warning')
        return False

    area = app.active_area
    if area is None:
        notify_and_log('Open an AI tab before turning the bot on.', type='negative')
        return False

    ready, reason = area.is_ready()
    if not ready:
        notify_and_log(reason or 'This area is not ready yet.', type='negative')
        return False

    app.powered_on = True
    status_badge.set_visibility(False)
    notify_and_log('Chatbot is now running!', type='positive', color='pink')
    return True


def run_startup_checks(app):
    if not winutil.is_running_as_admin():
        ui.notify('Not running as admin, some features <b>may not work</b>.', html=True, close_button='Close',
                  timeout=0, type='warning')

    if not winutil.is_condebug_in_game_args():
        ui.notify('Could not find <b>-condebug</b> in Steam CS2 launch arguments.', html=True, close_button='Close',
                  timeout=0, type='warning')
