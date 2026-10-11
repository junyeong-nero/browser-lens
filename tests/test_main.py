import unittest
import argparse
from unittest.mock import ANY, MagicMock, patch
import main


class TestMain(unittest.TestCase):

    @patch("main.argparse.ArgumentParser")
    @patch("main.PlaywrightBrowser")
    @patch("main.PlannerAgent")
    @patch("main.BrowserAgent")
    def test_main_playwright(
        self,
        mock_browser_agent,
        mock_planner_agent,
        mock_playwright_browser,
        mock_arg_parser,
    ):
        mock_args = MagicMock()
        mock_args.env = 'playwright'
        mock_args.initial_url = 'test_url'
        mock_args.search_engine_url = 'search_url'
        mock_args.highlight_mouse = True
        mock_args.headless = True
        mock_args.screen_size = (1280, 720)
        mock_args.query = 'test_query'
        mock_args.model = 'test_model'
        mock_args.log = True
        mock_args.video = False
        mock_args.ui_condition = None
        mock_args.grounding = "vision"
        mock_args.stealth = False
        mock_args.channel = None
        mock_args.user_agent = None
        mock_args.locale = None
        mock_args.timezone_id = None
        mock_args.proxy = None
        mock_args.storage_state = None
        mock_arg_parser.return_value.parse_args.return_value = mock_args
        mock_planner_agent.return_value.plan.return_value = []

        main.main()

        mock_playwright_browser.assert_called_once_with(
            screen_size=(1280, 720),
            initial_url='test_url',
            search_engine_url='search_url',
            highlight_mouse=True,
            headless=True,
            fit_window_to_screen=False,
            artifact_logger=ANY,
            channel=None,
            user_agent=None,
            locale=None,
            timezone_id=None,
            proxy=None,
            storage_state_path=None,
            stealth=False,
        )
        mock_browser_agent.assert_called_once()
        mock_browser_agent.return_value.agent_loop.assert_called_once()
        artifact_logger = mock_playwright_browser.call_args.kwargs["artifact_logger"]
        self.assertIsNotNone(artifact_logger.history_dir())
        self.assertIsNone(artifact_logger.video_dir())

    @patch("main.argparse.ArgumentParser")
    @patch("main.PlaywrightBrowser")
    @patch("main.PlannerAgent")
    @patch("main.BrowserAgent")
    def test_main_planner_passes_subgoals_and_replan_callback(
        self,
        mock_browser_agent,
        mock_planner_agent,
        mock_playwright_browser,
        mock_arg_parser,
    ):
        mock_args = MagicMock()
        mock_args.env = 'playwright'
        mock_args.initial_url = 'https://www.google.com'
        mock_args.search_engine_url = 'https://duckduckgo.com'
        mock_args.highlight_mouse = False
        mock_args.headless = False
        mock_args.screen_size = (1280, 720)
        mock_args.query = 'test_query'
        mock_args.model = 'test_model'
        mock_args.log = False
        mock_args.video = False
        mock_args.ui_condition = None
        mock_args.grounding = "vision"
        mock_args.stealth = False
        mock_args.channel = None
        mock_args.user_agent = None
        mock_args.locale = None
        mock_args.timezone_id = None
        mock_args.proxy = None
        mock_args.storage_state = None
        mock_arg_parser.return_value.parse_args.return_value = mock_args
        subgoals = [MagicMock()]
        mock_planner_agent.return_value.plan.return_value = subgoals

        main.main()

        mock_planner_agent.assert_called_once_with(query='test_query')
        call_kwargs = mock_browser_agent.call_args.kwargs
        self.assertIs(call_kwargs["subgoals"], subgoals)
        self.assertIs(call_kwargs["replan_callback"], mock_planner_agent.return_value.replan)
        self.assertEqual(call_kwargs["max_steps_per_subgoal"], main.app_config.max_steps_per_subgoal())
        self.assertEqual(call_kwargs["max_total_steps"], main.app_config.max_total_steps())
        self.assertEqual(call_kwargs["max_subgoals"], main.app_config.max_subgoals())

    @patch("main.argparse.ArgumentParser")
    @patch("main.PlaywrightBrowser")
    @patch("main.PlannerAgent")
    @patch("main.BrowserAgent")
    def test_main_planner_empty_plan_falls_back_to_actor_loop(
        self,
        mock_browser_agent,
        mock_planner_agent,
        mock_playwright_browser,
        mock_arg_parser,
    ):
        mock_args = MagicMock()
        mock_args.env = 'playwright'
        mock_args.initial_url = 'https://www.google.com'
        mock_args.search_engine_url = 'https://duckduckgo.com'
        mock_args.highlight_mouse = False
        mock_args.headless = False
        mock_args.screen_size = (1280, 720)
        mock_args.query = 'test_query'
        mock_args.model = 'test_model'
        mock_args.log = False
        mock_args.video = False
        mock_args.ui_condition = None
        mock_args.grounding = "vision"
        mock_args.stealth = False
        mock_args.channel = None
        mock_args.user_agent = None
        mock_args.locale = None
        mock_args.timezone_id = None
        mock_args.proxy = None
        mock_args.storage_state = None
        mock_arg_parser.return_value.parse_args.return_value = mock_args
        mock_planner_agent.return_value.plan.return_value = []

        with patch("main.emit") as mock_emit:
            main.main()

        call_kwargs = mock_browser_agent.call_args.kwargs
        self.assertIsNone(call_kwargs["subgoals"])
        self.assertIsNone(call_kwargs["replan_callback"])
        mock_browser_agent.return_value.agent_loop.assert_called_once()
        mock_emit.assert_any_call(
            {"type": "planner_fallback", "reason": "no valid subgoals returned"}
        )

    @patch("main.argparse.ArgumentParser")
    @patch("main.PlaywrightBrowser")
    @patch("main.PlannerAgent")
    @patch("main.BrowserAgent")
    def test_main_no_log(
        self,
        mock_browser_agent,
        mock_planner_agent,
        mock_playwright_browser,
        mock_arg_parser,
    ):
        mock_args = MagicMock()
        mock_args.env = 'playwright'
        mock_args.initial_url = 'https://www.google.com'
        mock_args.search_engine_url = 'https://duckduckgo.com'
        mock_args.highlight_mouse = False
        mock_args.headless = False
        mock_args.screen_size = (1280, 720)
        mock_args.query = 'test_query'
        mock_args.model = 'test_model'
        mock_args.log = False
        mock_args.video = False
        mock_args.ui_condition = None
        mock_args.grounding = "vision"
        mock_args.stealth = False
        mock_args.channel = None
        mock_args.user_agent = None
        mock_args.locale = None
        mock_args.timezone_id = None
        mock_args.proxy = None
        mock_args.storage_state = None
        mock_arg_parser.return_value.parse_args.return_value = mock_args
        mock_planner_agent.return_value.plan.return_value = []

        main.main()

        mock_playwright_browser.assert_called_once_with(
            screen_size=(1280, 720),
            initial_url='https://www.google.com',
            search_engine_url='https://duckduckgo.com',
            highlight_mouse=False,
            headless=False,
            fit_window_to_screen=True,
            artifact_logger=ANY,
            channel=None,
            user_agent=None,
            locale=None,
            timezone_id=None,
            proxy=None,
            storage_state_path=None,
            stealth=False,
        )

    @patch("main.argparse.ArgumentParser")
    @patch("main.PlaywrightBrowser")
    @patch("main.PlannerAgent")
    @patch("main.BrowserAgent")
    def test_main_video_only_enables_video_artifacts_without_history_log(
        self,
        mock_browser_agent,
        mock_planner_agent,
        mock_playwright_browser,
        mock_arg_parser,
    ):
        mock_args = MagicMock()
        mock_args.env = 'playwright'
        mock_args.initial_url = 'https://www.google.com'
        mock_args.search_engine_url = 'https://duckduckgo.com'
        mock_args.highlight_mouse = False
        mock_args.headless = False
        mock_args.screen_size = (1280, 720)
        mock_args.query = 'test_query'
        mock_args.model = 'test_model'
        mock_args.log = False
        mock_args.video = True
        mock_args.ui_condition = None
        mock_args.grounding = "vision"
        mock_args.stealth = False
        mock_args.channel = None
        mock_args.user_agent = None
        mock_args.locale = None
        mock_args.timezone_id = None
        mock_args.proxy = None
        mock_args.storage_state = None
        mock_arg_parser.return_value.parse_args.return_value = mock_args
        mock_planner_agent.return_value.plan.return_value = []

        main.main()

        artifact_logger = mock_playwright_browser.call_args.kwargs["artifact_logger"]
        self.assertIsNone(artifact_logger.history_dir())
        self.assertIsNotNone(artifact_logger.video_dir())

    @patch("main.detect_screen_size", return_value=(1440, 900))
    def test_resolve_screen_size_uses_detected_display_size(self, _mock_detect):
        self.assertEqual(main.resolve_screen_size(None), (1440, 900))

    @patch("main.detect_screen_size", return_value=None)
    def test_resolve_screen_size_falls_back_when_detection_fails(self, _mock_detect):
        self.assertEqual(main.resolve_screen_size(None), main.PLAYWRIGHT_SCREEN_SIZE)

    def test_parse_ui_condition_accepts_condition_aliases(self):
        self.assertEqual(main.parse_ui_condition("c1"), "c1_simple_ui")
        self.assertEqual(main.parse_ui_condition("c2"), "c2_browser_lens_no_graph")
        self.assertEqual(main.parse_ui_condition("c3"), "c3_browser_lens")
        self.assertEqual(main.parse_ui_condition("browserLens"), "c3_browser_lens")

    def test_parser_leaves_ui_condition_unset_until_validation(self):
        args = main._build_parser().parse_args([])

        self.assertIsNone(args.query)
        self.assertIsNone(args.ui_condition)
        self.assertFalse(hasattr(args, "ui_condition_explicit"))
        self.assertFalse(hasattr(args, "planner"))
        self.assertFalse(hasattr(args, "use_planner"))

    def test_parser_rejects_removed_planner_flags(self):
        parser = main._build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["--planner"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--no-planner"])

    def test_parser_rejects_removed_ui_flags(self):
        parser = main._build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["--ui"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--simple-ui"])

    def test_validate_args_allows_ui_condition_without_query(self):
        parser = MagicMock()
        args = argparse.Namespace(query=None, ui_condition="c1_simple_ui")

        main._validate_args(args, parser)

        parser.error.assert_not_called()
        self.assertEqual(args.ui_condition, "c1_simple_ui")

    def test_validate_args_rejects_ui_condition_with_query(self):
        parser = MagicMock()
        args = argparse.Namespace(query="test_query", ui_condition="c1_simple_ui")

        main._validate_args(args, parser)

        parser.error.assert_called_once_with(
            "--ui-condition is only used when the positional query is omitted."
        )

    def test_validate_args_allows_query_without_explicit_ui_condition(self):
        parser = MagicMock()
        args = argparse.Namespace(
            query="test_query",
            ui_condition=None,
        )

        main._validate_args(args, parser)

        parser.error.assert_not_called()
        self.assertEqual(args.ui_condition, main.DEFAULT_UI_CONDITION)

    @patch("main.webbrowser.open")
    @patch("main.threading.Thread")
    @patch("main.threading.Event")
    @patch("session.BrowserSession")
    def test_run_ui_mode_uses_requested_condition_server(
        self,
        mock_browser_session,
        mock_event,
        mock_thread,
        _mock_open,
    ):
        import ui.c1_simple_ui.server as c1_server

        ready = MagicMock()
        ready.wait.return_value = True
        mock_event.return_value = ready
        args = argparse.Namespace(
            ui_condition="c1",
            model="test_model",
            log=False,
            video=False,
            grounding="text",
        )

        main._run_ui_mode(MagicMock(), args)

        self.assertIs(mock_thread.call_args.kwargs["target"], c1_server.start)
        mock_thread.return_value.start.assert_called_once()
        self.assertTrue(mock_browser_session.call_args.kwargs["use_planner"])
        mock_browser_session.return_value.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
