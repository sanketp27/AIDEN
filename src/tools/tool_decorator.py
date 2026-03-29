"""
Tool decorator helper for ADK compatibility
Provides a @tool decorator that wraps functions as FunctionTool
"""
from google.adk.tools import FunctionTool
from typing import Callable, TypeVar, cast

T = TypeVar('T', bound=Callable)


def tool(func: T) -> T:
    """
    Decorator to mark a function as an ADK tool.

    This decorator is a compatibility shim that allows using the @tool syntax
    while the function gets wrapped as a FunctionTool when accessed.

    Usage:
        @tool
        async def my_function(arg: str) -> dict:
            return {"result": arg}
    """
    # Just return the function - it will be wrapped when used in Agent tools list
    return func


def wrap_tool(func: Callable) -> FunctionTool:
    """
    Wrap a function as a FunctionTool.

    Args:
        func: The function to wrap

    Returns:
        FunctionTool instance
    """
    return FunctionTool(func)
