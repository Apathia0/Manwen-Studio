"""开书引导相关单元测试"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


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
                "concept": "都市律政题材，律师主角从一桩离奇遗产案切入",
                "setting": "证据规则会影响现实，律师使用特殊能力必须承担记忆损耗",
                "tone": "律政、悬疑、轻喜剧",
                "goals": "长篇连载，面向喜欢律政悬疑的网文读者",
                "synthesis": "林衡，冷静严谨的青年律师，将从独善其身成长为规则改革者",
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
            assert result["understanding"]["concept"] == "都市律政题材，律师主角从一桩离奇遗产案切入"
            assert result["understanding_depth"] == 100
            assert result["has_brief"] is True

    @pytest.mark.asyncio
    async def test_merges_understanding(self):
        """应合并 understanding（保留旧字段，更新新字段）"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "更新理解",
            "understanding": {"tone": "都市、律政、轻喜剧"},
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
                understanding={"concept": "都市律政题材，律师主角从离奇遗产案切入"},
                api_key="test-key",
            )

            assert result["understanding"]["concept"] == "都市律政题材，律师主角从离奇遗产案切入"
            assert result["understanding"]["tone"] == "都市、律政、轻喜剧"
            assert result["understanding_depth"] == 40

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
                "concept": "都市律政题材，律师主角从离奇遗产案切入",
                "setting": "证据规则会影响现实，使用能力必须承担记忆损耗",
                "tone": "都市、律政、轻喜剧",
                "goals": "长篇连载，面向喜欢律政悬疑的网文读者",
                "synthesis": "林衡，冷静严谨的青年律师，将从独善其身成长为规则改革者",
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
                understanding={
                    "concept": "都市律政题材，律师主角从离奇遗产案切入",
                    "setting": "证据规则会影响现实，使用能力必须承担记忆损耗",
                    "tone": "都市、律政、轻喜剧",
                    "goals": "长篇连载，面向喜欢律政悬疑的网文读者",
                },
                api_key="test-key",
            )

            assert result["has_brief"] is True
            # creative_brief 现在由后端 _build_creative_brief_from_understanding
            # 在 confirm 阶段构建，AI 不输出 creative_brief
            assert result["creative_brief"] is None

    @pytest.mark.asyncio
    async def test_non_json_response_advances_current_field(self):
        """非 JSON 回复也应使用本轮用户回答推进当前字段。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": "好的，我们继续完善这个故事。"}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "力量来自与鬼签订契约"}],
                understanding={"concept": "都市诡异，程序员主角"},
                api_key="test-key",
            )

        assert result["understanding"] == {
            "concept": "都市诡异，程序员主角",
            "setting": "力量来自与鬼签订契约",
            "tone": "",
            "goals": "",
            "synthesis": "",
        }
        assert result["understanding_depth"] == 40
        assert result["phase"] == "refining"
        assert "风格标签" in result["reply"]

    @pytest.mark.asyncio
    async def test_truncated_json_preserves_partial_understanding(self):
        """截断 JSON 中已闭合的字段应被提取并规范化。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        content = (
            '{"reply":"继续","understanding":{"concept":"都市诡异",'
            '"setting":"契约体系","tone":"悬疑"'
        )
        mock_response = MagicMock()
        mock_response.text = json.dumps({"choices": [{"message": {"content": content}}]})
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "契约体系"}],
                understanding={"concept": "旧概念"},
                api_key="test-key",
            )

        assert result["understanding"] == {
            "concept": "都市诡异",
            "setting": "契约体系",
            "tone": "悬疑",
            "goals": "",
            "synthesis": "",
        }
        assert result["understanding_depth"] == 0


class TestOnboardingDecisionFlow:
    """用户要求 AI 建议时的候选决策与设定卡写入测试。"""

    def _setup_module_globals(self):
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @staticmethod
    def _screenshot_understanding() -> dict[str, str]:
        return {
            "concept": "都市高武题材，主角身份待定，开篇事件待补充",
            "setting": "你定",
            "tone": "热血、爽文、战斗、智斗",
            "goals": "中篇",
            "synthesis": "你定",
        }

    @pytest.mark.asyncio
    async def test_delegation_returns_choices_without_writing_placeholder(self):
        """“你定”只能触发建议，不能写入当前设定卡。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        decision = {
            "field": "concept",
            "question": "主角和开篇还不完整，请选择一个方向：",
            "options": [
                {
                    "id": "A",
                    "label": "武馆陪练",
                    "value": "都市高武题材，主角是底层武馆陪练，意外获得解析武技缺陷的能力，从地下擂台危机切入",
                    "reason": "升级线直接",
                },
                {
                    "id": "B",
                    "label": "管理局新人",
                    "value": "都市高武题材，主角是武道管理局新人，调查失控武者案件时发现力量体系背后的隐秘实验",
                    "reason": "兼顾悬疑调查",
                },
            ],
        }
        inner = {
            "reply": decision["question"],
            "understanding": self._screenshot_understanding(),
            "decision": decision,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "你帮我决定"}],
                understanding=self._screenshot_understanding(),
                api_key="test-key",
            )

        assert result["active_field"] == "concept"
        assert result["decision"]["field"] == "concept"
        assert len(result["decision"]["options"]) == 2
        assert result["understanding"] == self._screenshot_understanding()
        assert result["understanding_depth"] == 20
        assert set(result["incomplete_fields"]) == {"concept", "setting", "goals", "synthesis"}

    @pytest.mark.asyncio
    async def test_selected_option_updates_active_card(self):
        """用户选择后，完整方案应覆盖当前不完整卡片并继续检查下一张。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        selected = "都市高武题材，主角是底层武馆陪练，意外获得解析武技缺陷的能力，从地下擂台危机切入"
        inner = {
            "reply": "已写入故事概念，接下来补充世界观。",
            "understanding": {"concept": selected},
            "decision": None,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": selected}],
                understanding=self._screenshot_understanding(),
                api_key="test-key",
            )

        assert result["understanding"]["concept"] == selected
        assert result["active_field"] == "setting"
        assert result["understanding_depth"] == 40
        assert result["decision"] is None

    @pytest.mark.asyncio
    async def test_invalid_ai_decision_uses_contextual_fallback(self):
        """AI 未返回可用候选项时，回退方案仍应读取当前题材。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "我直接替你决定。",
            "understanding": {"concept": "你定"},
            "decision": None,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "你推荐几个"}],
                understanding=self._screenshot_understanding(),
                api_key="test-key",
            )

        assert result["decision"]["field"] == "concept"
        assert len(result["decision"]["options"]) == 3
        assert all("都市高武题材" in option["value"] for option in result["decision"]["options"])
        assert result["understanding"]["concept"].endswith("待补充")


class TestOnboardingGapQuestions:
    """部分答案必须被确认记录，并只追问当前字段的缺口。"""

    @staticmethod
    def _setup_module_globals():
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @staticmethod
    def _understanding(goals: str = "") -> dict[str, str]:
        return {
            "concept": "都市高武题材，外卖员主角意外卷入异常事件",
            "setting": "灵气来自城市裂隙，越级使用会造成精神反噬",
            "tone": "热血、悬疑、成长、群像",
            "goals": goals,
            "synthesis": "",
        }

    @pytest.mark.asyncio
    async def test_partial_goals_acknowledges_answer_and_only_asks_audience(self):
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "你计划写多长，主要面向哪类读者？",
            "understanding": {"goals": "中篇，网文"},
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "中篇，网文"}],
                understanding=self._understanding(),
                api_key="test-key",
            )

        assert result["understanding"]["goals"] == "中篇，网文"
        assert result["active_field"] == "goals"
        assert "已记录" in result["reply"]
        assert "中篇" in result["reply"]
        assert "网文" in result["reply"]
        assert "主要读者" in result["reply"]
        assert "写多长" not in result["reply"]

    @pytest.mark.asyncio
    async def test_followup_audience_merges_partial_goals_and_advances(self):
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "你计划写多长，主要面向哪类读者？",
            "understanding": {"goals": "男频升级"},
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "男频升级"}],
                understanding=self._understanding("中篇，网文"),
                api_key="test-key",
            )

        assert result["understanding"]["goals"] == "中篇，网文；男频升级"
        assert result["active_field"] == "synthesis"
        assert result["understanding_depth"] == 80
        assert "主角" in result["reply"]
        assert "写多长" not in result["reply"]

    @pytest.mark.asyncio
    async def test_followup_audience_is_used_when_model_repeats_previous_goals(self):
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        previous = self._understanding("中篇，网文")
        inner = {
            "reply": "你计划写多长，主要面向哪类读者？",
            "understanding": previous,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "男频升级"}],
                understanding=previous,
                api_key="test-key",
            )

        assert result["understanding"]["goals"] == "中篇，网文；男频升级"
        assert result["active_field"] == "synthesis"
        assert "主角" in result["reply"]
        assert "写多长" not in result["reply"]

    @pytest.mark.asyncio
    async def test_followup_audience_is_used_when_model_reformats_previous_goals(self):
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        previous = self._understanding("中篇，网文")
        reformatted = dict(previous, goals="中篇、网文")
        inner = {
            "reply": "你计划写多长，主要面向哪类读者？",
            "understanding": reformatted,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "男频升级"}],
                understanding=previous,
                api_key="test-key",
            )

        assert result["understanding"]["goals"].endswith("男频升级")
        assert result["active_field"] == "synthesis"
        assert "主角" in result["reply"]
        assert "写多长" not in result["reply"]


class TestOnboardingConfirm:
    """引导确认的提交边界测试。"""

    def _setup_module_globals(self):
        """设置 deepseek 模块全局变量，供本文件后续响应测试复用。"""
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @staticmethod
    def _understanding() -> dict[str, str]:
        return {
            "concept": "都市诡异题材，程序员主角被卷入契约事件",
            "setting": "通过契约获得力量，使用能力必须承担代价",
            "tone": "都市、诡异、悬疑、写实",
            "goals": "长篇连载，面向悬疑网文读者",
            "synthesis": "林默，冷静谨慎，从逃避成长为主动守护同伴的人",
        }

    @staticmethod
    def _story() -> SimpleNamespace:
        return SimpleNamespace(
            id=1,
            title="测试故事",
            description="",
            story_bible=None,
            story_memory=None,
            tags={},
            characters=[],
            outline={},
            onboarding_completed=False,
        )

    @pytest.mark.asyncio
    async def test_framework_failure_does_not_complete_onboarding(self):
        """框架生成失败时不得提前提交 Story Bible 或完成状态。"""
        import main as app_main
        from fastapi import HTTPException

        story = self._story()
        user = SimpleNamespace(id=7)
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "understanding": self._understanding(),
            "messages": [{"role": "user", "content": "开始生成"}],
        })
        db = MagicMock()
        bible = {
            "creative_brief": {
                "one_line_premise": self._understanding()["concept"],
                "serial_length_target": self._understanding()["goals"],
            },
            "raw_input": {"raw_idea": self._understanding()["concept"]},
        }

        with (
            patch.object(app_main, "_require_user", return_value=user),
            patch.object(app_main, "_require_story_for_user", return_value=story),
            patch.object(app_main, "_check_and_consume_advanced_text_quota"),
            patch.object(app_main, "_check_and_consume_feature_quota"),
            patch.object(app_main, "_user_deepseek_api_key", return_value="test-key"),
            patch.object(app_main, "_release_db_transaction"),
            patch.object(app_main, "get_effective_prompt", return_value=None),
            patch.object(app_main, "get_template_story_length", return_value="long"),
            patch.object(app_main, "build_story_bible", AsyncMock(return_value=bible)),
            patch.object(
                app_main,
                "generate_framework",
                AsyncMock(side_effect=ValueError("无有效 JSON")),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await app_main.onboarding_confirm(1, request, db)

        assert exc_info.value.status_code == 502
        assert story.onboarding_completed is False
        assert story.story_bible is None
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_incomplete_understanding_before_ai_calls(self):
        """五字段未补齐时应直接拒绝确认，避免生成空框架。"""
        import main as app_main
        from fastapi import HTTPException

        story = self._story()
        request = MagicMock()
        request.json = AsyncMock(return_value={
            "understanding": {"concept": "只有一个概念"},
            "messages": [],
        })
        db = MagicMock()

        with (
            patch.object(app_main, "_require_user", return_value=SimpleNamespace(id=7)),
            patch.object(app_main, "_require_story_for_user", return_value=story),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await app_main.onboarding_confirm(1, request, db)

        assert exc_info.value.status_code == 422
        db.commit.assert_not_called()


class TestGenerateOnboardingResponseNormalization:
    """引导回复规范化与安全回退测试。"""

    def _setup_module_globals(self):
        """设置 deepseek 模块全局变量，避免鉴权辅助函数报错。"""
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @pytest.mark.asyncio
    async def test_server_derives_progress_and_ignores_model_claims(self):
        """完成度和分析卡状态必须由规范化字段推导。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "已经完成",
            "understanding": {"concept": "都市悬疑", "setting": "规则世界"},
            "understanding_depth": 100,
            "phase": "synthesizing",
            "has_brief": True,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "规则世界"}],
                understanding={"concept": "都市悬疑"},
                api_key="test-key",
            )

        assert result["understanding_depth"] == 0
        assert result["phase"] == "extracting"
        assert result["has_brief"] is False

    @pytest.mark.asyncio
    async def test_generation_command_cannot_trigger_framework_content(self):
        """生成指令不应成为字段内容，也不应透传模型生成的框架正文。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "第一幕：主角进入诡异公司，随后开始升级。",
            "understanding": {},
            "understanding_depth": 100,
            "phase": "synthesizing",
            "has_brief": True,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200
        mock_client_class = _mock_async_client(mock_response)

        with patch("services.deepseek.httpx.AsyncClient", mock_client_class):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "直接生成框架"}],
                understanding={"concept": "都市诡异"},
                api_key="test-key",
            )

        assert result["understanding"] == {
            "concept": "都市诡异",
            "setting": "",
            "tone": "",
            "goals": "",
            "synthesis": "",
        }
        assert "第一幕" not in result["reply"]
        assert "已记录" in result["reply"]
        assert "都市诡异" in result["reply"]
        assert "主角" in result["reply"]
        payload = mock_client_class.return_value.__aenter__.return_value.post.await_args.kwargs["json"]
        assert payload["response_format"] == {"type": "json_object"}
        assert "禁止生成框架、正文、大纲或样章" in payload["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_empty_and_unknown_fields_do_not_overwrite_previous_state(self):
        """空值、未知字段和非字符串字段不得污染已确认理解。"""
        self._setup_module_globals()
        from services.deepseek import generate_onboarding_response

        inner = {
            "reply": "继续确认",
            "understanding": {
                "concept": "",
                "setting": None,
                "tone": "悬疑",
                "unknown": "不应保留",
            },
            "has_brief": True,
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        mock_response.status_code = 200

        with patch("services.deepseek.httpx.AsyncClient", _mock_async_client(mock_response)):
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "确认"}],
                understanding={"concept": "都市诡异", "setting": "契约规则", "legacy": "旧字段"},
                api_key="test-key",
            )

        assert result["understanding"] == {
            "concept": "都市诡异",
            "setting": "契约规则",
            "tone": "悬疑",
            "goals": "",
            "synthesis": "",
        }
        assert result["understanding_depth"] == 0


class TestBuildStoryBibleStructure:
    """build_story_bible 对 creative_brief 缺失的重试与兜底。

    背景：AI 在 JSON mode 下可能返回合法 JSON 但漏掉 creative_brief 键，
    导致 onboarding/confirm 端点校验失败（502「AI 返回的 Story Bible 结构不完整」）。
    """

    def _setup_module_globals(self):
        """设置 deepseek 模块全局变量，供 runtime_base_url/runtime_model 读取。"""
        import services.deepseek as ds
        ds.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        ds.DEEPSEEK_MODEL = "deepseek-chat"

    @staticmethod
    def _brief() -> dict[str, str]:
        return {
            "one_line_premise": "程序员卷入诡异契约事件",
            "genre": "都市诡异",
            "audience": "悬疑网文读者",
        }

    @staticmethod
    def _raw_input() -> dict[str, str]:
        return {
            "raw_idea": "程序员卷入诡异契约事件",
            "raw_length_goal": "长篇连载",
            "raw_must_keep": "保留契约代价设定",
        }

    @staticmethod
    def _mock_response(inner: dict[str, object]) -> MagicMock:
        """构造 DeepSeek chat/completions 响应 mock。"""
        resp = MagicMock()
        resp.text = json.dumps({
            "choices": [{"message": {"content": json.dumps(inner, ensure_ascii=False)}}]
        })
        resp.status_code = 200
        return resp

    @staticmethod
    def _mock_client_with_responses(responses: list[MagicMock]) -> MagicMock:
        """构造按顺序返回多个响应的 AsyncClient mock。"""
        mock_client_instance = MagicMock()
        mock_client_instance.post = AsyncMock(side_effect=responses)
        mock_class = MagicMock()
        mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_class.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_class

    @pytest.mark.asyncio
    async def test_missing_creative_brief_triggers_retry(self):
        """AI 漏掉 creative_brief 时应触发修复重试，而非直接返回残缺结构。"""
        self._setup_module_globals()
        from services.deepseek import build_story_bible

        incomplete = {
            "story_bible": {
                "raw_input": {"raw_idea": "程序员卷入诡异契约事件"},
                "writing_guidance": {"opening_strategy": "以契约触发事件开篇"},
            }
        }
        complete = {
            "story_bible": {
                "raw_input": {"raw_idea": "程序员卷入诡异契约事件"},
                "creative_brief": self._brief(),
                "writing_guidance": {"opening_strategy": "以契约触发事件开篇"},
            }
        }
        client_class = self._mock_client_with_responses([
            self._mock_response(incomplete),
            self._mock_response(complete),
        ])

        with patch("services.deepseek.httpx.AsyncClient", client_class):
            result = await build_story_bible(
                self._brief(), self._raw_input(), api_key="test-key",
            )

        post_mock = client_class.return_value.__aenter__.return_value.post
        assert post_mock.await_count == 2
        assert result["creative_brief"] == self._brief()
        assert result["writing_guidance"] == {"opening_strategy": "以契约触发事件开篇"}

    @pytest.mark.asyncio
    async def test_backfills_creative_brief_after_final_attempt(self):
        """两轮都缺 creative_brief 时应回填入参创意卡，保证返回结构可用。"""
        self._setup_module_globals()
        from services.deepseek import build_story_bible

        incomplete = {
            "story_bible": {
                "raw_input": {"raw_idea": "程序员卷入诡异契约事件"},
                "writing_guidance": {"opening_strategy": "以契约触发事件开篇"},
            }
        }
        client_class = self._mock_client_with_responses([
            self._mock_response(incomplete),
            self._mock_response(incomplete),
        ])

        with patch("services.deepseek.httpx.AsyncClient", client_class):
            result = await build_story_bible(
                self._brief(), self._raw_input(), api_key="test-key",
            )

        assert result["creative_brief"] == self._brief()

    @pytest.mark.asyncio
    async def test_ai_creative_brief_kept_when_present(self):
        """AI 正常返回 creative_brief 时应原样保留，不被入参覆盖，也不触发重试。"""
        self._setup_module_globals()
        from services.deepseek import build_story_bible

        ai_brief = dict(self._brief(), one_line_premise="AI 重新提炼的一句话")
        complete = {
            "story_bible": {
                "raw_input": {"raw_idea": "程序员卷入诡异契约事件"},
                "creative_brief": ai_brief,
                "writing_guidance": {"opening_strategy": "以契约触发事件开篇"},
            }
        }
        client_class = self._mock_client_with_responses([self._mock_response(complete)])

        with patch("services.deepseek.httpx.AsyncClient", client_class):
            result = await build_story_bible(
                self._brief(), self._raw_input(), api_key="test-key",
            )

        post_mock = client_class.return_value.__aenter__.return_value.post
        assert post_mock.await_count == 1
        assert result["creative_brief"] == ai_brief
