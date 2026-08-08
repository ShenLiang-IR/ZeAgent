def __getattr__(name):
    _lazy = {
        'BaseExecutor': '.base_executor',
        'DeepAgentExecutor': '.deep_agent_executor',
        'ExecutorFactory': '.factory',
        'SqlTemplateExecutor': '.sql_template_executor',
        'SqlTemplateResult': '.sql_template_executor',
    }
    if name in _lazy:
        import importlib
        module = importlib.import_module(_lazy[name], __package__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
__all__ = [
    'BaseExecutor',
    'DeepAgentExecutor',
    'ExecutorFactory',
    'SqlTemplateExecutor',
    'SqlTemplateResult',
]