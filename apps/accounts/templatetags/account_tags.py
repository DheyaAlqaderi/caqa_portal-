from django import template

register = template.Library()

@register.filter(name='dict_get')
def dict_get(dictionary, key):
    if not dictionary or not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)

@register.filter(name='get_item')
def get_item(dictionary, key):
    if not dictionary or not isinstance(dictionary, dict):
        return None
    return dictionary.get(key)
