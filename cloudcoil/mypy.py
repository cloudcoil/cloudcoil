from typing import Callable, Optional

import mypy
from mypy.nodes import (
    Expression,
    StrExpr,
    TypeInfo,
)
from mypy.plugin import FunctionContext, Plugin
from mypy.types import Instance, TypeType
from mypy.types import Type as MypyType

from cloudcoil import resources


class ResourcePlugin(Plugin):
    def __init__(self, options):
        super().__init__(options)
        resources._Scheme._initialize()

    def get_function_hook(self, fullname: str) -> Optional[Callable[[FunctionContext], MypyType]]:
        if fullname == "cloudcoil.resources.get_model":
            return self._analyze_get
        return None

    def _extract_str_literal(self, expr: Expression) -> Optional[str]:
        """Extract string literal value if expression is a string literal."""
        if isinstance(expr, StrExpr):
            return expr.value
        return None

    def get_additional_deps(self, file: mypy.nodes.MypyFile):
        # This is a hack to make sure that mypy knows about all registered modules
        return [(10, module_name, -1) for module_name in resources._Scheme._registered_modules]

    def _analyze_get(self, context: FunctionContext) -> MypyType:
        if not context.args:
            context.api.fail("resources.get_model requires at least one argument", context.context)
            return context.default_return_type

        # Find the kind and api_version arguments based on position or name
        kind_arg = None
        api_version_arg = None
        for arg_name, arg_expr in zip(context.arg_names, context.args, strict=False):
            if arg_name == "kind":
                kind_arg = arg_expr[0]
            elif arg_name == "api_version":
                api_version_arg = arg_expr[0]

        # If not found by name, try positional
        if kind_arg is None and context.args:
            kind_arg = context.args[0][0]
        if api_version_arg is None and len(context.args) > 1 and context.args[1]:
            api_version_arg = context.args[1][0]

        if not kind_arg:
            return context.default_return_type
        kind = self._extract_str_literal(kind_arg)
        api_version = self._extract_str_literal(api_version_arg) if api_version_arg else None
        api_version = api_version or ""
        if not kind:
            return context.default_return_type

        cls = resources.get_model(api_version=api_version, kind=kind)
        qualname = f"{cls.__module__}.{cls.__qualname__}"
        # Lookup the fully qualified name to get the TypeInfo
        # This is a bit of a hack as we are able to lookup the TypeInfo
        # based on the fully qualified name because we are loading
        # the module in the get_additional_deps method
        symbol = self.lookup_fully_qualified(qualname)
        if not symbol or not symbol.node:
            return context.default_return_type
        if not isinstance(symbol.node, TypeInfo):
            return context.default_return_type
        return TypeType(Instance(symbol.node, []))


def plugin(_: str):
    return ResourcePlugin
