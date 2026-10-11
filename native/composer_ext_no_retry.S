/* ColorOS 17.0.0.114 libcomposer_ext.so, ClientImpl::Init at 0x18ac8.
 * Replace only the null-service branch after tryGetService/temporary cleanup.
 * Destination 0x18eb8 is the original -EHOSTDOWN return and stack epilogue.
 * Keep the valid-service path; skip missing-MTK-service retries on Ranchu.
 * The complete ELF hashes and original bytes are pinned in native_patches.py.
 */
.text
.global coloros_avd_missing_composer
.type coloros_avd_missing_composer, %function
coloros_avd_missing_composer:
    cbz x8, . + 0x3f0
.size coloros_avd_missing_composer, .-coloros_avd_missing_composer
