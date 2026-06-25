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

        with ui.grid(columns=2).classes('gap-4 w-full'):
            with settings_card('Appearance'):
                ui.switch('Dark Theme', value=saved.get('dark_theme', True),
                          on_change=lambda e: set_theme(e.value))

                with ui.row().classes('items-center gap-2'):
                    with ui.button(icon='colorize').props('rounded'):
                        ui.color_picker(on_pick=lambda e: set_color(e.color))
                    ui.label('Accent color').classes('text-sm opacity-70')

            with settings_card('Chatbot'):
                delay_input = ui.number('Wait before responding (ms)', value=app.response_delay_ms,
                                        min=0, step=50, format='%.0f',
                                        on_change=lambda e: set_ms('response_delay_ms', e.value)) \
                    .classes('w-full')
                with delay_input:
                    ui.tooltip('Fixed pause before the bot sends a reply, simulating thinking time.')

                jitter_input = ui.number('Jitter range (ms)', value=app.response_jitter_ms,
                                         min=0, step=50, format='%.0f',
                                         on_change=lambda e: set_ms('response_jitter_ms', e.value)) \
                    .classes('w-full')
                with jitter_input:
                    ui.tooltip('A random amount between 0 and this is added on top of the wait, '
                               'so the delay varies each time.')

                auto_switch = ui.switch('Auto-press execute key', value=app.auto_press,
                                        on_change=lambda e: set_flag('auto_press', e.value))
                with auto_switch:
                    ui.tooltip('When on, the bot presses your bind key in-game. When off, the '
                               'bot only writes message.cfg — press it yourself (watch the exec light).')

                cooldown_switch = ui.switch('Reply cooldown', value=app.cooldown_enabled,
                                            on_change=lambda e: set_flag('cooldown_enabled', e.value))
                with cooldown_switch:
                    ui.tooltip('When on, the bot waits at least the cooldown below between replies, '
                               'across every area — useful against command spam.')

                cooldown_input = ui.number('Cooldown (ms)', value=app.cooldown_ms,
                                           min=0, step=100, format='%.0f',
                                           on_change=lambda e: set_ms('cooldown_ms', e.value)) \
                    .classes('w-full')
                with cooldown_input:
                    ui.tooltip('Minimum time between any two bot replies when the cooldown is on.')

            self._token_section(app)
            self._roster_section(app)

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
                          on_change=lambda e, n=name: app.roster.__setitem__(n, e.value))

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
                        ui.button('Clear', icon='delete', on_click=clear).props('outline dense')
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

        with ui.row().classes('items-center gap-2 w-full'):
            token_input = ui.input(label=field.label, password=True,
                                   on_change=lambda e: on_change(e.value)).classes('w-64')
            if help_dialog is not None:
                ui.button(icon='help', on_click=help_dialog.open).props('rounded')

        # Restore the saved value; setting .value fires on_change -> persist + on_set.
        saved = app.load_area_settings(area.key).get(field.key)
        if saved:
            token_input.value = saved
