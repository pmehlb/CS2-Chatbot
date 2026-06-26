"""The Settings area: appearance, chatbot timing, API tokens and the live
player roster.

It implements the same ChatArea contract as the chat behaviours and gets its
tab the same way (registered in areas/__init__.py), but sets ``answerable =
False`` so selecting its tab idles the bot instead of routing chat to it.
"""
from nicegui import ui

from ui.ui_util import settings_card
from .base import ChatArea


class SettingsArea(ChatArea):
    key = 'settings'
    label = 'Settings'
    icon = 'settings'
    answerable = False  # a utility tab, not a chat behaviour: it never replies

    async def generate(self, message: str, app):
        # Never reached while answerable is False; defined for safety/clarity.
        return None

    def build_tab(self, app) -> None:
        saved = app.load_app_settings()
        theme = app.theme

        def set_theme(on):
            theme.enable() if on else theme.disable()
            app.save_app_setting('dark_theme', on)

        def set_color(color):
            ui.colors(primary=color)
            app.save_app_setting('primary_color', color)

        def set_flag(name, value):
            setattr(app, name, value)
            app.save_app_setting(name, value)

        def set_ms(name, value):
            set_flag(name, max(0, int(value or 0)))

        # Cards fill the 2-col grid left -> right, top -> bottom:
        #   Logic | Known Players  /  API Tokens | Appearance.
        with ui.grid(columns=2).classes('gap-4 w-full'):
            with settings_card('Logic'):
                # The two timing fields sit side by side (50% / 50%); the cooldown
                # field stays full-width below, grouped with its own switch.
                with ui.grid(columns=2).classes('gap-3 w-full'):
                    delay_input = ui.number('Respond Delay (ms)', value=app.response_delay_ms,
                                            min=0, step=50, format='%.0f',
                                            on_change=lambda e: set_ms('response_delay_ms', e.value))
                    with delay_input:
                        ui.tooltip('Fixed pause before the bot sends a reply (to stimulate thinking/typing time).')

                    jitter_input = ui.number('Respond Jitter (ms)', value=app.response_jitter_ms,
                                             min=0, step=50, format='%.0f',
                                             on_change=lambda e: set_ms('response_jitter_ms', e.value))
                    with jitter_input:
                        ui.tooltip('Random time between 0 - X ms added to the respond delay (to simulate variance).')

                # Reply-cooldown switch and its number box share one 50% / 50% row.
                with ui.grid(columns=2).classes('gap-3 w-full items-center'):
                    cooldown_switch = ui.switch('Cooldown', value=app.cooldown_enabled,
                                                on_change=lambda e: set_flag('cooldown_enabled', e.value)) \
                        .props('dense')
                    with cooldown_switch:
                        ui.tooltip('Bot waits at least the cooldown below between replies (useful against command spam).')

                    cooldown_input = ui.number('Cooldown (ms)', value=app.cooldown_ms,
                                               min=0, step=100, format='%.0f',
                                               on_change=lambda e: set_ms('cooldown_ms', e.value)) \
                        .classes('w-full')
                    with cooldown_input:
                        ui.tooltip('Minimum time between any two bot replies when the cooldown is on.')

                auto_switch = ui.switch('Auto-press execute key', value=app.auto_press,
                                        on_change=lambda e: set_flag('auto_press', e.value)) \
                    .props('dense')
                with auto_switch:
                    ui.tooltip('When on, the bot presses your bind key in-game. When off, the '
                               'bot only writes message.cfg — press it yourself (watch the exec light).')

                self._keybind_row(app, set_flag)

            self._roster_section(app)
            self._token_section(app)

            with settings_card('Appearance'):
                ui.switch('Dark Theme', value=saved.get('dark_theme', True),
                          on_change=lambda e: set_theme(e.value)).props('dense')

                with ui.row().classes('items-center gap-2'):
                    with ui.button(icon='colorize').props('rounded'):
                        ui.color_picker(on_pick=lambda e: set_color(e.color))
                    ui.label('Accent color').classes('text-sm opacity-70')

    def _keybind_row(self, app, set_flag):
        """Render the global enable/disable hotkey control inside the Logic card.

        Press-to-record: clicking Set pauses the live hotkey, awaits one keypress
        (in a worker thread), then re-registers and persists it. A refreshable row
        keeps the shown key in sync after Set/Clear.
        """
        if not app.hotkeys.available:
            ui.label('Toggle keybind unavailable (keyboard library not loaded).') \
                .classes('text-sm text-grey')
            return

        @ui.refreshable
        def row():
            with ui.row().classes('items-center gap-2 w-full'):
                key = app.toggle_key
                with ui.row().classes('items-center gap-1'):
                    ui.label('App Toggle:').classes('text-sm')
                    ui.label(key if key else '(not set)').classes('text-sm font-bold')

                set_btn = ui.button('Set', icon='keyboard').props('outline dense') \
                    .classes('ml-auto').style('padding-left: 8px; padding-right: 4px')
                with set_btn:
                    ui.tooltip('A system-wide key that turns the bot on/off — works while CS2 '
                               'is focused. Click, then press the key you want.')

                async def record():
                    set_btn.set_text('Press a key…')
                    set_btn.props('loading')
                    app.hotkeys.clear()              # pause the live hotkey while recording
                    recorded = await app.hotkeys.record()
                    target = recorded or app.toggle_key   # empty -> keep the old binding
                    app.hotkeys.rebind(target)
                    set_flag('toggle_key', target)
                    row.refresh()

                set_btn.on('click', record)

                if app.toggle_key:
                    def clear():
                        app.hotkeys.rebind('')
                        set_flag('toggle_key', '')
                        row.refresh()
                    ui.button('Clear', icon='delete', on_click=clear).props('outline dense') \
                        .style('padding-left: 8px; padding-right: 4px')

        row()

    def _roster_section(self, app):
        """Render the live 'Known Players' card: one toggle per person seen in chat.

        The roster lives on ``app`` and is mutated by the chat loop as new people
        talk. This card mirrors it: a refreshable body redrawn whenever the roster
        version changes (a ~1s timer polls it), with toggles writing straight back
        into ``app.roster`` and a Clear button to forget everyone.
        """

        @ui.refreshable
        def roster_list():
            if not app.roster:
                ui.label('No one has talked yet.').classes('text-sm text-grey')
                return
            for name in app.roster:
                ui.switch(name, value=app.roster[name],
                          on_change=lambda e, n=name: app.roster.__setitem__(n, e.value)).props('dense')

        def clear():
            app.roster.clear()
            app.roster_version += 1
            roster_list.refresh()

        last_version = app.roster_version

        def poll():
            nonlocal last_version
            if app.roster_version != last_version:
                last_version = app.roster_version
                roster_list.refresh()

        with ui.card().tight().classes('shadow-sm shadow-black'):
            with ui.card_section().classes('w-full'):
                with ui.column().classes('gap-3 w-full'):
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.badge('Known Players')
                        ui.button('Clear', icon='delete', on_click=clear).props('outline dense') \
                            .style('padding-left: 8px; padding-right: 4px')
                    roster_list()

        # Redraw the list when the chat loop adds someone (or it's cleared).
        ui.timer(1.0, poll)

    def _token_section(self, app):
        """Render the 'API Tokens' card from every area's declared TokenFields.

        The areas own the secrets (via on_set); this section owns the input widgets
        and persistence. Only shown if at least one area declares a token.
        """
        fields = [(area, field) for area in app.areas for field in area.tokens()]
        if not fields:
            return

        with settings_card('API Tokens'):
            for area, field in fields:
                self._token_input(app, area, field)

    def _token_input(self, app, area, field):
        help_dialog = None
        if field.help_md:
            with ui.dialog() as help_dialog, ui.card():
                ui.markdown(field.help_md)
                ui.button('Close', on_click=help_dialog.close).props('outline')

        async def on_change(value):
            # Read-merge so multiple fields in one area's namespace don't clobber.
            data = app.load_area_settings(area.key)
            data[field.key] = value
            app.save_area_settings(area.key, data)
            await field.on_set(value)

        with ui.row().classes('items-center gap-2 w-full no-wrap'):
            token_input = ui.input(label=field.label, password=True,
                                   on_change=lambda e: on_change(e.value)) \
                .props('hide-bottom-space').classes('grow')
            if help_dialog is not None:
                ui.button(icon='help', on_click=help_dialog.open).props('round dense size=sm')

        # Restore the saved value; setting .value fires on_change -> persist + on_set.
        saved = app.load_area_settings(area.key).get(field.key)
        if saved:
            token_input.value = saved
