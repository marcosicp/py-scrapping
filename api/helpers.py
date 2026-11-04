import re

def remove_duplicates_by_key(objects_list, key):
    unique_keys = set()
    new_objects_list = []

    for obj in objects_list:
        if obj[key] not in unique_keys:
            unique_keys.add(obj[key])
            new_objects_list.append(obj)

    return new_objects_list

def name_parse(name):
    # Patrón de expresión regular para buscar el peso o volumen en formato "1kg", "500 ml", "1 lt" o "2 lt"
    # -- the quantity may be a decimal ("1.5 lts", "1,5 lts") or an "X2" pack;
    # -- without the decimal part the pattern matched "5 lts" inside "1.5 lts"
    # -- and corrupted the name (review R3-002).
    #patron_peso_volumen = r"\b(\d+|X\d+)\s*(kg|kgs|g|gr|grs|ml|mls|m|cc|lt|lts)\b"
    patron_peso_volumen = (r"(\d+(?:[.,]\d+)?|X\d+)\s*"
                           r"(kg|kgs|g|gr|grs|ml|mls|m|cc|lt|lts)\b")

    concatenated_result=''
    resultados = re.findall(patron_peso_volumen, name, re.IGNORECASE)
    if (resultados):
        # -- re.escape: a decimal quantity carries a literal dot
        name = re.sub(r"\b" + re.escape(resultados[0][0]) + r"\s*"
                      + re.escape(resultados[0][1]) + r"\b", "", name)
        name = re.sub(r",\s*,", ",", name)
        name = re.sub(r"\s{2,}", " ", name)
        
        name = name.strip()
        
        concatenated_result = ", ".join([f"{cantidad} {unidad}" for cantidad, unidad in resultados])
        
        
    # resultParsed = resultados.con
    return {"name": name, "unidad": concatenated_result}
