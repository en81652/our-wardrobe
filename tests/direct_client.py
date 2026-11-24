"""Socket-free route harness, deliberately NOT an HTTP/ASGI integration test.

Opt in only with WARDROBE_TEST_DIRECT=1 on hosts that disallow sockets.
Normal test runs still use Starlette TestClient.
"""
import inspect
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError


class Result:
    def __init__(self, status, data):
        self.status_code = status
        self.data = data
        self.text = str(data)
        self.content = Path(data.path).read_bytes() if isinstance(data, FileResponse) else b""

    def json(self):
        return self.data


class DirectClient:
    def __init__(self, app, headers):
        self.routes = []
        self.headers = headers
        def collect(routes):
            for route in routes:
                if hasattr(route, "original_router"):
                    collect(route.original_router.routes)
                elif hasattr(route, "endpoint"):
                    self.routes.append(route)
        collect(app.routes)

    def close(self):
        pass

    def request(self, method, url, json=None):
        from starlette.routing import Match
        parsed = urlsplit(url)
        scope = {"type": "http", "path": parsed.path, "method": method, "root_path": ""}
        for route in self.routes:
            match, child = route.matches(scope)
            if match != Match.FULL:
                continue
            try:
                for dependency in route.dependencies:
                    dependency.dependency(self.headers.get("Authorization"))
                values = {**child.get("path_params", {}), **{key: value[0] for key, value in parse_qs(parsed.query).items()}}
                signature = inspect.signature(route.endpoint)
                for name, parameter in signature.parameters.items():
                    annotation = parameter.annotation
                    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                        values[name] = annotation.model_validate(json)
                    elif name in values and isinstance(parameter.default, int):
                        values[name] = int(values[name])
                return Result(route.status_code or 200, route.endpoint(**values))
            except HTTPException as error:
                return Result(error.status_code, {"detail": error.detail})
            except ValidationError as error:
                return Result(422, {"detail": str(error)})
        return Result(404, {"detail": "route not found"})

    def get(self, url):
        return self.request("GET", url)

    def post(self, url, json):
        return self.request("POST", url, json)

    def patch(self, url, json):
        return self.request("PATCH", url, json)

    def delete(self, url):
        return self.request("DELETE", url)
