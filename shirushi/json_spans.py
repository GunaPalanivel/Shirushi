"""Locate exact JSON value tokens by object/array path."""
import json


def span(raw, path):
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()

    def whitespace(position):
        while position < len(text) and text[position].isspace():
            position += 1
        return position

    def walk(position, remaining):
        position = whitespace(position)
        if not remaining:
            _, end = decoder.raw_decode(text, position)
            return text[position:end]
        target, *rest = remaining
        opening = text[position]
        position = whitespace(position + 1)
        index = 0
        while text[position] not in ']}':
            if opening == '{':
                key, position = decoder.raw_decode(text, position)
                position = whitespace(position)
                if text[position] != ':':
                    raise ValueError('Invalid JSON separator')
                position = whitespace(position + 1)
            elif opening == '[':
                key = index
            else:
                raise ValueError('Path descends through a scalar')
            if type(key) is type(target) and key == target:
                return walk(position, rest)
            _, position = decoder.raw_decode(text, position)
            position = whitespace(position)
            if text[position] == ',':
                position = whitespace(position + 1)
            index += 1
        raise ValueError('JSON path absent')

    return walk(0, list(path))
