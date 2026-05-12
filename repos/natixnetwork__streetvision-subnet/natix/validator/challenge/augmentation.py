from natix.utils.image_transforms import apply_augmentation_by_level


def augment_challenge(image, size, mask_center):
    return apply_augmentation_by_level(image, size, mask_center)
