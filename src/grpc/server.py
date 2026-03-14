"""
Dummy gRPC server: forwards RPCs to MainEngine.

Run with a MainEngine instance; the server translates dashboard/control
calls into put_event, handle_intent, and engine getters. Stub only:
actual gRPC serving and codegen (grpc_tools.protoc) to be wired when needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class GrpcServer:
    """
    Dummy gRPC server that holds a reference to MainEngine.

    Intended usage:
        server = GrpcServer(main_engine=main)
        server.run(port=50051)  # when implemented
    """

    def __init__(self, main_engine: "MainEngine") -> None:
        self._main = main_engine

    def run(self, host: str = "0.0.0.0", port: int = 50051) -> None:
        """Start the gRPC server (stub: not implemented)."""
        raise NotImplementedError("gRPC server.run() not implemented; add grpcio and codegen.")
