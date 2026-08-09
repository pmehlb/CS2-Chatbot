"""The Settings area: appearance, chatbot timing, command rules, API tokens and
the live player roster.

It implements the same ChatArea contract as the chat behaviors and gets its
tab the same way (registered in areas/__init__.py), but sets ``answerable =
False`` so selecting its tab idles the bot instead of routing chat to it.
"""
import json
import os
import time

from nicegui import ui

import rules
from system import gsi
from ui.ui_util import notify_and_log, settings_card
from .base import ChatArea


class SettingsArea(ChatArea):
    key = 'settings'
    label = 'Settings'
    icon = 'settings'
    answerable = False  # a utility tab, not a chat behavior: it never replies

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

                attribute_switch = ui.switch('Attribute messages to speakers', value=app.attribute_speakers,
                                             on_change=lambda e: set_flag('attribute_speakers', e.value)) \
                    .props('dense')
                with attribute_switch:
                    ui.tooltip('When on, each chat message is fed to the AI chatbots as '
                               '"[Name] said: message" so replies can track who said what. '
                               'Does not affect the Command Bot or Reverser.')

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

        # Command rules and GSI setup both span the full width below the grid:
        # each is a list/setup flow that would be cramped in a half-width card.
        self._rules_section(app)
        self._gsi_section(app)

    def _rules_section(self, app):
        """Render the 'Command Rules' card: labels a bot writes into its own
        reply, pointed at what the app should do with them.

        The rules are global -- every area's reply runs through them in the chat
        loop -- so they live here with the other cross-cutting settings and
        persist in the app namespace rather than in any one area's.
        """

        @ui.refreshable
        def rule_list():
            if not app.rules:
                # An empty state that shows the shape of a rule beats one that only
                # reports the absence of any.
                ui.label('No rules yet — add one above, e.g. SILENT → stay silent.') \
                    .classes('text-sm opacity-70')
                return
            # Tighter than the card's gap-3: these are list rows, not sibling controls.
            with ui.column().classes('gap-1 w-full'):
                for i, rule in enumerate(app.rules):
                    # px-2/-mx-2 bleeds the hover band into the card padding so the
                    # text still lines up with everything above it. The tint is a
                    # translucent grey rather than an accent: it has to read on both
                    # the light and dark themes, and Tailwind has no 'primary'
                    # (that's a Quasar colour, and it would silently render nothing).
                    with ui.row().classes('items-center gap-2 w-full no-wrap rounded '
                                          'px-2 -mx-2 py-1 hover:bg-gray-500/10 transition-colors'):
                        # Same width as the Command input above, so the arrows line
                        # up in a column instead of zig-zagging with label length.
                        ui.label(f"([{rules.normalize_label(rule.get('label'))}])") \
                            .classes('font-mono text-sm w-36 shrink-0 truncate')
                        ui.icon('arrow_forward').classes('text-sm opacity-50 shrink-0')

                        detail = ui.label(rules.describe_rule(rule)) \
                            .classes('text-sm opacity-80 truncate min-w-0 grow')
                        if (rule.get('text') or '').strip():
                            with detail:      # the reply text can outrun the row
                                ui.tooltip(rules.describe_rule(rule))

                        ui.button(icon='delete', on_click=lambda idx=i: remove(idx)) \
                            .props('flat round dense color=grey').classes('shrink-0')

        @ui.refreshable
        def snippet():
            text = rules.prompt_snippet(app.rules)
            if not text:
                return
            with ui.expansion('Prompt snippet', icon='content_paste',
                              caption="Paste into your bot's system prompt so it "
                                      "knows which labels it may use") \
                    .classes('w-full').props('dense'):
                with ui.column().classes('gap-2 w-full'):
                    # Monospace: this is text to be pasted verbatim, so the labels
                    # should read as literal strings rather than prose.
                    ui.textarea(value=text).props('readonly autogrow outlined dense') \
                        .classes('w-full font-mono text-xs')
                    ui.button('Copy', icon='content_copy',
                              on_click=lambda t=text: self._copy(t)) \
                        .props('outline dense').style('padding-left: 8px; padding-right: 8px')

        def save():
            app.save_app_setting('rules', app.rules)
            rule_list.refresh()
            snippet.refresh()

        def remove(idx: int):
            if 0 <= idx < len(app.rules):
                app.rules.pop(idx)
                save()

        with settings_card('Command Rules'):
            ui.markdown('Point a label your bot writes into its reply — like `([SILENT])` — '
                        'at an action. Labels with no rule are sent to chat unchanged.') \
                .classes('area-desc text-sm opacity-70')

            with ui.row().classes('items-center gap-2 w-full no-wrap'):
                label_input = ui.input('Command', placeholder='SILENT') \
                    .props('hide-bottom-space').classes('w-36')
                with label_input:
                    ui.tooltip('The label name. Brackets are optional — SILENT, [SILENT] '
                               'and ([SILENT]) all mean the same rule.')

                action_select = ui.select(rules.ACTIONS, value=rules.ACTION_SILENT,
                                          label='Action').props('hide-bottom-space').classes('w-36')
                with action_select:
                    ui.tooltip('Stay silent drops the whole reply. Say this swaps the '
                               'label for your text and keeps the rest of the sentence.')

                text_input = ui.input('Say this', placeholder='get good') \
                    .props('hide-bottom-space').classes('grow')
                text_input.set_enabled(False)   # the default action is "stay silent"
                action_select.on_value_change(
                    lambda e: text_input.set_enabled(e.value == rules.ACTION_SAY))

                def add():
                    label = rules.normalize_label(label_input.value)
                    if not label:
                        notify_and_log('Enter a command label first.', type='warning')
                        return
                    if any(rules.normalize_label(r.get('label')) == label for r in app.rules):
                        notify_and_log(f'A rule for ([{label}]) already exists.', type='warning')
                        return

                    action = action_select.value or rules.ACTION_SILENT
                    text = (text_input.value or '').strip() if action == rules.ACTION_SAY else ''
                    app.rules.append({'label': label, 'action': action, 'text': text})
                    save()
                    label_input.value = ''
                    text_input.value = ''
                    # Rules get added in runs; put the caret back where the next
                    # one starts instead of making the user re-click the box.
                    label_input.run_method('focus')

                label_input.on('keydown.enter', add)
                text_input.on('keydown.enter', add)
                ui.button(icon='add', on_click=add).props('rounded')

            rule_list()
            snippet()

    @staticmethod
    def _copy(text: str) -> None:
        """Copy ``text`` to the clipboard from the webview.

        NiceGUI 1.4 has no clipboard helper, so this goes through JS.
        navigator.clipboard needs a secure context -- localhost qualifies, but
        the hidden-textarea fallback covers the case where it doesn't.
        """
        ui.run_javascript(f'''
            const text = {json.dumps(text)};
            if (navigator.clipboard && window.isSecureContext) {{
                navigator.clipboard.writeText(text);
            }} else {{
                const el = document.createElement('textarea');
                el.value = text;
                el.style.position = 'fixed';
                el.style.opacity = '0';
                document.body.appendChild(el);
                el.select();
                document.execCommand('copy');
                document.body.removeChild(el);
            }}
        ''')
        notify_and_log('Prompt snippet copied.', type='positive')

    def _gsi_section(self, app):
        """Full-width Game State Integration setup card.

        GSI is app-wide -- Tilt Bot and any AI area that opts into reacting to
        game events use it -- so its one-time setup lives here in Settings rather
        than on a single behavior's tab.
        """
        with settings_card('Game State Integration (GSI)'):
            ui.label('Lets the bot react to your live game events (multi-kills, MVPs, '
                     'clutches). Install the config, then fully restart CS2 to activate.') \
                .classes('text-sm opacity-70')
            install_btn = ui.button('Install GSI config', icon='download',
                                    on_click=lambda: self._install_gsi(app)).props('outline')
            with install_btn:
                ui.tooltip("Writes gamestate_integration_cs2chatbot.cfg into CS2's cfg folder.")

            # Where the config goes and which local endpoint CS2 posts to, so the
            # setup is transparent (and debuggable if a taunt never fires).
            cfg_path = os.path.join(app.cs_path, 'cfg', gsi.GSI_CFG_NAME)
            ui.label(f'Endpoint: 127.0.0.1:{gsi.GSI_PORT}/gsi').classes('text-xs opacity-60')
            ui.label(f'Config: {cfg_path}').classes('text-xs opacity-60 break-all')

            # Live connection light: confirms CS2 is actually POSTing to us, so
            # setup success is visible without waiting for a taunt to fire.
            with ui.row().classes('items-center gap-2'):
                self._gsi_icon = ui.icon('circle').classes('text-sm').props('color=grey')
                self._gsi_label = ui.label('Waiting for CS2…').classes('text-sm opacity-70')
            ui.timer(1.0, lambda: self._refresh_gsi(app))

    def _refresh_gsi(self, app):
        """Poll GSI freshness and recolour the connection light (1s timer)."""
        receiving = gsi.is_receiving(app, time.monotonic())
        self._gsi_icon.props(f'color={"green" if receiving else "grey"}')
        self._gsi_label.text = 'Receiving game data' if receiving else 'Waiting for CS2…'

    def _install_gsi(self, app):
        try:
            path = gsi.write_gsi_cfg(app)
            notify_and_log(f'Installed GSI config — restart CS2 to activate. ({path})',
                           type='positive')
        except OSError as e:
            notify_and_log(f'Could not write GSI config: {e}', type='negative')

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
