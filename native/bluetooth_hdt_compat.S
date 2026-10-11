/* Audited replacement for the ColorOS 17.0.0.114 ARM64
 * ControllerImpl::impl::read_local_hdt_features_handler prologue.
 * Rootcanal has no OPPO HDT extension; leave local_hdt_features_ unsupported.
 * This does not bypass standard controller initialization or HCI validation.
 * scripts/native_patches.py verifies the complete library and original bytes.
 */
.text
.global coloros_avd_read_local_hdt_features
.type coloros_avd_read_local_hdt_features, %function
coloros_avd_read_local_hdt_features:
    bti c
    strb wzr, [x0, #0x184]
    ret
.size coloros_avd_read_local_hdt_features, .-coloros_avd_read_local_hdt_features
