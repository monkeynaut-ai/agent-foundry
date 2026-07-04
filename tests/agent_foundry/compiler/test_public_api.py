"""Public-API export guarantees for compiler extension points."""

import agent_foundry.compiler as compiler


def test_compiler_extension_points_are_publicly_exported():
    from agent_foundry.compiler import (
        CompileContext,
        CompileResult,
        compile_process,
        register_compiler,
    )

    expected = {
        "CompileContext",
        "CompileResult",
        "compile_process",
        "register_compiler",
    }

    assert expected <= set(compiler.__all__)
    assert compiler.CompileContext is CompileContext
    assert compiler.CompileResult is CompileResult
    assert compiler.compile_process is compile_process
    assert compiler.register_compiler is register_compiler
