def remove_duplicates_by_key(objects_list, key):
    unique_keys = set()
    new_objects_list = []

    for obj in objects_list:
        if obj[key] not in unique_keys:
            unique_keys.add(obj[key])
            new_objects_list.append(obj)

    return new_objects_list