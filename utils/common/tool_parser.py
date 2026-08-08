import inspect
import re
from typing import Dict, Any
def format_type_annotation(annotation: Any) -> str:
    if annotation is None or annotation == inspect.Parameter.empty:
        return 'Any'
    if isinstance(annotation, type):
        return annotation.__name__
    elif hasattr(annotation, '__name__'):
        return annotation.__name__
    elif hasattr(annotation, '__origin__'):
        origin = annotation.__origin__
        args = getattr(annotation, '__args__', ())
        if args:
            arg_names = []
            for arg in args:
                if isinstance(arg, type):
                    arg_names.append(arg.__name__)
                elif hasattr(arg, '__name__'):
                    arg_names.append(arg.__name__)
                else:
                    arg_names.append(str(arg))
            if hasattr(origin, '__name__'):
                return f"{origin.__name__}[{', '.join(arg_names)}]"
            else:
                return f"{origin}[{', '.join(arg_names)}]"
        else:
            if hasattr(origin, '__name__'):
                return origin.__name__
            else:
                return str(origin)
    else:
        type_str = str(annotation)
        if type_str.startswith("<class '") and type_str.endswith("'>"):
            return type_str[8:-2]
        elif type_str.startswith("<class ") and type_str.endswith(">"):
            return type_str[7:-1].strip("'\"")
        return type_str
def parse_docstring(docstring: str) -> Dict[str, Any]:
    if not docstring:
        return {
            'description': '',
            'parameter_descriptions': {},
            'return_description': '',
            'examples': []
        }
    docstring = docstring.strip()
    lines = docstring.split('\n')
    description = ''
    description_lines = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith(':') or line.startswith(':') or line.startswith(':'):
            break
        description_lines.append(line)
    description = ' '.join(description_lines).strip()
    parameter_descriptions = {}
    in_params_section = False
    param_lines = []
    current_param = None
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_original = line
        if line_stripped.startswith(':'):
            in_params_section = True
            continue
        if in_params_section:
            if line_stripped.startswith(':') or line_stripped.startswith(':'):
                if current_param and param_lines:
                    parameter_descriptions[current_param] = ' '.join(param_lines).strip()
                break
            if not line_stripped:
                if current_param and param_lines:
                    parameter_descriptions[current_param] = ' '.join(param_lines).strip()
                    current_param = None
                    param_lines = []
                continue
            param_match = re.match(r'^\s*(\w+)\s*[:]\s*(.+)$', line_stripped)
            if param_match:
                if current_param and param_lines:
                    parameter_descriptions[current_param] = ' '.join(param_lines).strip()
                current_param = param_match.group(1)
                param_desc = param_match.group(2).strip()
                param_lines = [param_desc] if param_desc else []
            elif current_param:
                if line_original.startswith(' ') or line_original.startswith('\t'):
                    param_lines.append(line_stripped)
                else:
                    if param_lines:
                        parameter_descriptions[current_param] = ' '.join(param_lines).strip()
                    current_param = None
                    param_lines = []
    if current_param and param_lines:
        parameter_descriptions[current_param] = ' '.join(param_lines).strip()
    return_description = ''
    in_return_section = False
    return_lines = []
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith(':'):
            in_return_section = True
            continue
        if in_return_section:
            if line_stripped.startswith(':'):
                break
            if line_stripped:
                return_lines.append(line_stripped)
    return_description = ' '.join(return_lines).strip()
    examples = []
    in_examples_section = False
    example_lines = []
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith(':'):
            in_examples_section = True
            continue
        if in_examples_section:
            if line_stripped:
                if '->' in line_stripped or '→' in line_stripped:
                    if example_lines:
                        examples.append(' '.join(example_lines).strip())
                        example_lines = []
                    examples.append(line_stripped)
                else:
                    example_lines.append(line_stripped)
    if example_lines:
        examples.append(' '.join(example_lines).strip())
    return {
        'description': description,
        'parameter_descriptions': parameter_descriptions,
        'return_description': return_description,
        'examples': examples
    }
def extract_tool_info(tool: Any) -> Dict[str, Any]:
    tool_name = None
    if hasattr(tool, 'name'):
        tool_name = tool.name
    elif hasattr(tool, '__name__'):
        tool_name = tool.__name__
    else:
        tool_name = str(tool)
    func = tool
    if hasattr(tool, 'func'):
        func = tool.func
    elif hasattr(tool, '__wrapped__'):
        func = tool.__wrapped__
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        sig = None
    parameters = []
    if sig:
        for param_name, param in sig.parameters.items():
            param_info = {
                'name': param_name,
                'type': format_type_annotation(param.annotation),
                'default': param.default if param.default != inspect.Parameter.empty else None,
                'required': param.default == inspect.Parameter.empty
            }
            parameters.append(param_info)
    return_type = 'str'
    if sig and sig.return_annotation != inspect.Signature.empty:
        return_type = format_type_annotation(sig.return_annotation)
    docstring = None
    if hasattr(func, '__doc__') and func.__doc__:
        docstring = func.__doc__
    elif hasattr(tool, 'description'):
        docstring = tool.description
    doc_info = parse_docstring(docstring) if docstring else {
        'description': '',
        'parameter_descriptions': {},
        'return_description': '',
        'examples': []
    }
    for param in parameters:
        param_name = param['name']
        if param_name in doc_info['parameter_descriptions']:
            param['description'] = doc_info['parameter_descriptions'][param_name]
        else:
            param['description'] = ''
    return {
        'name': tool_name,
        'display_name': '',
        'description': doc_info['description'],
        'parameters': parameters,
        'return_type': return_type,
        'return_description': doc_info['return_description'],
        'examples': doc_info['examples'],
        'parameter_descriptions': doc_info['parameter_descriptions'],
        'invoke': hasattr(tool, 'invoke')
    }