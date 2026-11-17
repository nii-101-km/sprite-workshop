"""Remove invisible alpha noise from a copy of the Idol input."""


def prepare_idol_source(image, alpha_threshold=8):
    if type(alpha_threshold) is not int or not 0 <= alpha_threshold <= 254:
        raise ValueError('Порог непрозрачности должен быть целым числом от 0 до 254')
    result = image.copy()
    if result.mode != 'RGBA':
        return result
    alpha = result.getchannel('A')
    if alpha.getextrema()[0] == 255:
        return result
    cleaned = alpha.point(lambda value: 0 if value <= alpha_threshold else value)
    if cleaned.getbbox() is None:
        raise ValueError('Для 3D нужен непустой исходник')
    result.putalpha(cleaned)
    return result
