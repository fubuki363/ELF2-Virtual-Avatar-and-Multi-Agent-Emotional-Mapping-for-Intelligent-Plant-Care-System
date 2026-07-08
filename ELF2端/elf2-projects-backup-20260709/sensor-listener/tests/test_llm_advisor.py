"""Tests for LLMAdvisor."""
import pytest
from unittest import mock
from sensor_listener.llm_advisor import LLMAdvisor


def make_data(**overrides):
    defaults = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1000}
    defaults.update(overrides)
    return defaults


class TestLLMAdvisor:
    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        advisor = LLMAdvisor(api_key="test-key")
        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = TimeoutError()
            result = await advisor.consult(
                "soil > 2500",
                [make_data(soil=2600, ts=1000), make_data(soil=2700, ts=2000)],
                {"health": 60, "trends": {}, "alerts": []},
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_decision_on_success(self):
        advisor = LLMAdvisor(api_key="test-key")
        mock_response = mock.MagicMock()
        mock_response.choices = [
            mock.MagicMock(
                message=mock.MagicMock(
                    content='{"actions":[{"d":"fan","v":60},{"d":"pump","v":30}],"reason":"温度偏高且土壤偏干","confidence":0.85}'
                )
            )
        ]

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create = mock.AsyncMock(return_value=mock_response)
            result = await advisor.consult(
                "温度上升",
                [make_data(t=31.0, ts=1000), make_data(t=32.0, ts=2000)],
                {"health": 55, "trends": {"t": 0.02}, "alerts": ["温度偏高"]},
            )

        assert result is not None
        assert len(result.commands) == 2
        assert result.reason == "温度偏高且土壤偏干"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_handles_malformed_json_response(self):
        advisor = LLMAdvisor(api_key="test-key")
        mock_response = mock.MagicMock()
        mock_response.choices = [mock.MagicMock(message=mock.MagicMock(content="not valid json"))]

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create = mock.AsyncMock(return_value=mock_response)
            result = await advisor.consult("测试", [make_data()], {"health": 80, "trends": {}, "alerts": []})

        assert result is None  # Should fallback on parse error

    @pytest.mark.asyncio
    async def test_consecutive_failures_pause(self):
        advisor = LLMAdvisor(api_key="test-key", max_failures=3, pause_seconds=0.1)

        with mock.patch("openai.AsyncOpenAI") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = TimeoutError()

            # 3 failures
            for _ in range(3):
                result = await advisor.consult("test", [make_data()], {"health": 80, "trends": {}, "alerts": []})
                assert result is None

            # 4th should be paused
            result = await advisor.consult("test", [make_data()], {"health": 80, "trends": {}, "alerts": []})
            assert result is None  # Paused, not even called

    def test_trigger_condition_dry_soil(self):
        advisor = LLMAdvisor(api_key="test-key")
        history = [make_data(soil=s, ts=i*1000) for i, s in enumerate(range(2500, 2600))]
        # Soil > 2500 for more than 10 seconds
        assert advisor.should_consult("soil_dry", history) is True

    def test_trigger_condition_rapid_heat(self):
        advisor = LLMAdvisor(api_key="test-key")
        history = [make_data(t=25.0 + i*0.02, ts=i*1000) for i in range(300)]  # +6°C over 5 minutes
        assert advisor.should_consult("temp_rising", history) is True
