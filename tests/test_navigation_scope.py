import unittest

from core.navigation_scope import NavigationScope


class NavigationScopeInferenceTest(unittest.TestCase):
    def test_technical_dot_tokens_do_not_create_site_scope(self):
        queries = [
            "node.js fs 문서를 검색해서 요약해줘",
            "main.py 오류 해결 방법을 찾아줘",
            "config.yaml 설정 예시를 찾아줘",
        ]

        for query in queries:
            with self.subTest(query=query):
                self.assertIsNone(NavigationScope.from_query(query))

    def test_site_domain_still_creates_site_scope(self):
        scope = NavigationScope.from_query("allrecipes.com에서 pasta 검색")

        self.assertIsNotNone(scope)
        assert scope is not None
        self.assertEqual(
            scope.allowed_hosts,
            frozenset({"allrecipe.com", "allrecipes.com"}),
        )


if __name__ == "__main__":
    unittest.main()
