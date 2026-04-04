import json
import re

json_path = r'c:\Users\ddeni\Downloads\axon_models_config.json'
config_path = r'c:\Users\ddeni\OneDrive\Documents\WORKSPACE\Axon-AI\axon\config.py'

with open(json_path, 'r', encoding='utf-8') as f:
    json_data = json.load(f)

json_models = json_data['axon_ai']['models']

python_str = '    MODEL_SLOTS = [\n'
for i, m in enumerate(json_models):
    m_dict = {
        'id': int(m['id']),
        'name': m['name'],
        'model_id': m['model_id'],
        'style': m['style'],
        'accent': m['accent'],
        'description': m['description'],
        'capabilities': m['capabilities'],
        'sampling': m['sampling']
    }
    
    # Format dict nicely
    formatted_dict = json.dumps(m_dict, indent=4, ensure_ascii=False)
    # Add indentation offset
    lines = formatted_dict.split('\n')
    lines = ['        ' + line if j > 0 else line for j, line in enumerate(lines)]
    formatted_dict = '        ' + '\n'.join(lines)
    
    # fix booleans manually
    formatted_dict = formatted_dict.replace("false", "False").replace("true", "True")
    
    python_str += formatted_dict
    if i < len(json_models) - 1:
        python_str += ',\n'
    else:
        python_str += '\n    ]\n'


with open(config_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the array
content = re.sub(r'    MODEL_SLOTS = \[\n.*?\n    \]', lambda m: python_str.strip('\n'), content, flags=re.DOTALL)

with open(config_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated config.py slots successfully!")
