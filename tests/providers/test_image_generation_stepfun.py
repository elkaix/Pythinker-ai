"""Focused tests for the StepFun image generation client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pythinker.providers.image_generation import (
    ImageGenerationError,
    StepFunImageGenerationClient,
    image_gen_provider_names,
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
RAW_B64 = PNG_DATA_URL.split(",", 1)[1]


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.request = httpx.Request("POST", "https://api.stepfun.com/v1/images/generations")

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, text=self.text)
            raise httpx.HTTPStatusError("failed", request=self.request, response=response)


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_image_gen_provider_names_includes_stepfun() -> None:
    names = image_gen_provider_names()
    assert "stepfun" in names
    # Tuple is the registration order; openrouter is registered first.
    assert names[0] == "openrouter"


@pytest.mark.asyncio
async def test_stepfun_payload_and_response_with_aspect_ratio() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a cat on the moon",
        model="step-image-edit-2",
        aspect_ratio="16:9",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://api.stepfun.com/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-sf-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "step-image-edit-2"
    assert body["prompt"] == "a cat on the moon"
    assert body["response_format"] == "b64_json"
    assert body["n"] == 1
    assert body["size"] == "1280x800"


@pytest.mark.asyncio
async def test_stepfun_default_size_when_no_aspect_ratio() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="a dog", model="step-image-edit-2")

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_stepfun_uses_explicit_image_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a bird",
        model="step-image-edit-2",
        image_size="1024x1024",
    )

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_stepfun_style_reference_on_1x_model(tmp_path: Path) -> None:
    """step-1x-medium supports style_reference for reference-image generation."""
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="in this style",
        model="step-1x-medium",
        reference_images=[str(ref)],
    )

    body = fake.calls[0]["json"]
    assert "style_reference" in body
    assert body["style_reference"]["source_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_stepfun_no_style_reference_on_non_1x_model() -> None:
    """step-image-edit-2 does not use style_reference; reference images are ignored."""
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a flower",
        model="step-image-edit-2",
        reference_images=["/tmp/ref.png"],
    )

    body = fake.calls[0]["json"]
    assert "style_reference" not in body


@pytest.mark.asyncio
async def test_stepfun_requires_api_key() -> None:
    client = StepFunImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="step-image-edit-2")


@pytest.mark.asyncio
async def test_stepfun_no_images_raises() -> None:
    fake = FakeClient(FakeResponse({"data": [{"text": "sorry"}]}))
    client = StepFunImageGenerationClient(api_key="sk-sf-test", client=fake)  # type: ignore[arg-type]

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="step-image-edit-2")
