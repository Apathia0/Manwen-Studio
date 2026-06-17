"""开书引导相关单元测试"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestUnderstandingModel:
    """Understanding 模型测试"""

    def test_understanding_default_values(self):
        """Understanding 默认值应为空字符串"""
        from schemas import Understanding
        u = Understanding()
        assert u.concept == ""
        assert u.setting == ""
        assert u.tone == ""
        assert u.goals == ""
        assert u.synthesis == ""

    def test_understanding_with_values(self):
        """Understanding 应支持赋值"""
        from schemas import Understanding
        u = Understanding(
            concept="都市律师",
            setting="规则怪谈世界",
            tone="偏喜剧",
            goals="长篇连载",
            synthesis="一个关于规则与漏洞的故事",
        )
        assert u.concept == "都市律师"
        assert u.synthesis == "一个关于规则与漏洞的故事"


class TestOnboardingMessageOut:
    """OnboardingMessageOut 模型测试"""

    def test_has_new_fields(self):
        """应包含新的 understanding 字段"""
        from schemas import OnboardingMessageOut, Understanding
        out = OnboardingMessageOut(
            reply="test",
            understanding=Understanding(concept="test"),
            understanding_depth=50,
            phase="exploring",
            has_brief=False,
        )
        assert out.understanding.concept == "test"
        assert out.understanding_depth == 50
        assert out.phase == "exploring"
        assert out.has_brief is False

    def test_has_compatibility_fields(self):
        """应保留兼容字段"""
        from schemas import OnboardingMessageOut
        out = OnboardingMessageOut(
            reply="test",
            collected_info={"story_concept": "test"},
            step=1,
            total_steps=5,
            is_complete=False,
        )
        assert out.collected_info == {"story_concept": "test"}
        assert out.step == 1
        assert out.is_complete is False


def _mock_async_client(mock_response: MagicMock) -> MagicMock:
    """构造 AsyncClient mock（async context manager）"""
    mock_client_instance = MagicMock()
    mock_client_instance.post = AsyncMock(return_value=mock_response)

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_class


class TestGenerateOnboardingResponse:
    """generate_onboarding_response 函数测试"""

    def _setup_module_globals(self):
        """设置 deepseek 模块全局变量，避免 _deepseek_auth_headers 报错"""
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @pytest.mark.asyncio
    async def test_returns_understanding_structure(self):
        """应返回 understanding 结构"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "这是一个关于律师的故事",
            "understanding": {
                "concept": "都市律师题材",
                "setting": "规则怪谈世界",
                "tone": "偏喜剧",
                "goals": "长篇连载",
                "synthesis": "一个关于规则与漏洞的故事",
            },
            "understanding_depth": 60,
            "phase": "exploring",
            "has_brief": False,
            "creative_brief": None,
        }

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "我想写个律师的故事"}],
                understanding={},
                api_key="test-key",
            )

            assert "understanding" in result
            assert result["understanding"]["concept"] == "都市律师题材"
            assert result["understanding_depth"] == 60
            assert result["has_brief"] is False

    @pytest.mark.asyncio
    async def test_merges_understanding(self):
        """应合并 understanding（保留旧字段，更新新字段）"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "更新理解",
            "understanding": {"tone": "偏喜剧"},
            "understanding_depth": 70,
            "phase": "refining",
            "has_brief": False,
            "creative_brief": None,
        }

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "偏喜剧"}],
                understanding={"concept": "都市律师"},
                api_key="test-key",
            )

            assert result["understanding"]["concept"] == "都市律师"
            assert result["understanding"]["tone"] == "偏喜剧"

    @pytest.mark.asyncio
    async def test_has_brief_when_depth_high(self):
        """深度足够时应输出分析卡"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        brief = {
            "project_positioning": "都市律师题材",
            "genre": "都市",
            "audience": "青年读者",
        }

        inner = {
            "reply": "我已经理解了你的想法",
            "understanding": {
                "concept": "都市律师",
                "setting": "规则怪谈世界",
                "tone": "偏喜剧",
                "goals": "长篇连载",
                "synthesis": "综合理解",
            },
            "understanding_depth": 85,
            "phase": "synthesizing",
            "has_brief": True,
            "creative_brief": brief,
        }

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "确认"}],
                understanding={"concept": "都市律师", "setting": "规则怪谈", "tone": "喜剧", "goals": "长篇"},
                api_key="test-key",
            )

            assert result["has_brief"] is True
            assert result["creative_brief"]["project_positioning"] == "都市律师题材"
