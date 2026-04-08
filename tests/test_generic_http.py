"""Tests for kickforge_gsi.adapters.generic_http module."""

import json

import httpx
import pytest

from kickforge_gsi.adapters.generic_http import GenericHTTPAdapter


class TestGenericHTTPAdapter:
    @pytest.fixture
    def adapter(self):
        return GenericHTTPAdapter(base_url="http://localhost:9999")

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, adapter):
        await adapter.connect()
        assert adapter.is_connected is True
        await adapter.disconnect()
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_execute_post(self):
        captured = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, text="ok")

        adapter = GenericHTTPAdapter(base_url="http://test", method="POST")
        adapter._http = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        )
        adapter._connected = True
        result = await adapter.execute("/api/cmd", {"command": "spawn"})
        assert result == "ok"
        assert captured["method"] == "POST"
        assert captured["body"]["command"] == "spawn"
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_execute_get(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert "key=val" in str(request.url)
            return httpx.Response(200, text="got it")

        adapter = GenericHTTPAdapter(base_url="http://test", method="GET")
        adapter._http = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        )
        adapter._connected = True
        result = await adapter.execute("/api/query", {"key": "val"})
        assert result == "got it"
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_execute_not_connected(self, adapter):
        with pytest.raises(ConnectionError):
            await adapter.execute("/test", {})

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        adapter = GenericHTTPAdapter(base_url="http://test")
        adapter._http = httpx.AsyncClient(
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        )
        adapter._connected = True
        with pytest.raises(ConnectionError):
            await adapter.execute("/api/fail", {})
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_get_state(self):
        adapter = GenericHTTPAdapter(base_url="http://test")
        await adapter.connect()
        state = await adapter.get_state()
        assert state["connected"] is True
        assert state["base_url"] == "http://test"
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_custom_headers(self):
        captured_headers = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, text="ok")

        adapter = GenericHTTPAdapter(
            base_url="http://test",
            headers={"X-Custom": "myvalue"},
        )
        adapter._http = httpx.AsyncClient(
            base_url="http://test",
            headers={"X-Custom": "myvalue"},
            transport=httpx.MockTransport(handler),
        )
        adapter._connected = True
        await adapter.execute("/api", {})
        assert captured_headers.get("x-custom") == "myvalue"
        await adapter.disconnect()
