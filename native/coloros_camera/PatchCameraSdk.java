import java.util.*;
import com.android.tools.smali.dexlib2.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.instruction.formats.Instruction35c;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.reference.*;
import com.android.tools.smali.dexlib2.builder.*;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.writer.pool.*;

/**
 * Patch the ColorOS camera unit SDK by class and method name.
 *
 * Args: input.dex output.dex helper.dex expected-counts, where expected-counts
 * is "edit=count,..." for every edit. The SDK keeps its class names, so the
 * edits do not depend on byte offsets of one firmware.
 */
public final class PatchCameraSdk {
    private static final String HELPER = "Lcom/coloros/avd/camera/VirtualCameraSdk;";
    private static final String APS = "Lcom/oplus/ocs/camera/consumer/apsAdapter/";
    private static final String INFO = "Lcom/oplus/ocs/camera/producer/info/";
    private static final Map<String, Integer> counts = new TreeMap<>();

    public static void main(String[] args) throws Exception {
        DexFile source = DexFileFactory.loadDexFile(args[0], Opcodes.forApi(28));
        DexPool pool = new DexPool(Opcodes.forApi(28));
        for (ClassDef cls : source.getClasses()) {
            List<Method> methods = new ArrayList<>();
            for (Method method : cls.getMethods()) {
                MethodImplementation old = method.getImplementation();
                MutableMethodImplementation code = old == null ? null : patch(cls.getType(), method, old);
                methods.add(code == null ? method : new ImmutableMethod(method.getDefiningClass(), method.getName(),
                    method.getParameters(), method.getReturnType(), method.getAccessFlags(), method.getAnnotations(),
                    method.getHiddenApiRestrictions(), code));
            }
            pool.internClass(new ImmutableClassDef(cls.getType(), cls.getAccessFlags(), cls.getSuperclass(),
                cls.getInterfaces(), cls.getSourceFile(), cls.getAnnotations(), cls.getFields(), methods));
        }
        Map<String, Integer> expected = new TreeMap<>();
        for (String item : args[3].split(",")) expected.put(item.split("=")[0], Integer.parseInt(item.split("=")[1]));
        if (!counts.equals(expected)) throw new IllegalStateException("Expected camera SDK edits " + expected + ", found " + counts);
        for (ClassDef cls : DexFileFactory.loadDexFile(args[2], Opcodes.forApi(28)).getClasses()) pool.internClass(cls);
        pool.writeTo(new com.android.tools.smali.dexlib2.writer.io.FileDataStore(new java.io.File(args[1])));
        System.out.println("Patched camera SDK " + counts);
    }

    private static boolean refers(Instruction ins, Class<? extends Reference> kind, String owner, String name) {
        if (!(ins instanceof ReferenceInstruction)) return false;
        Reference ref = ((ReferenceInstruction) ins).getReference();
        if (ref instanceof FieldReference && kind == FieldReference.class)
            return ((FieldReference) ref).getDefiningClass().equals(owner) && ((FieldReference) ref).getName().equals(name);
        if (ref instanceof MethodReference && kind == MethodReference.class)
            return ((MethodReference) ref).getDefiningClass().equals(owner) && ((MethodReference) ref).getName().equals(name);
        return false;
    }

    private static MethodReference helper(String name, String result, String... params) {
        return new ImmutableMethodReference(HELPER, name, Arrays.asList(params), result);
    }

    private static void hit(String edit) {
        counts.merge(edit, 1, Integer::sum);
    }

    private static MutableMethodImplementation patch(String type, Method method, MethodImplementation old) {
        MutableMethodImplementation code = new MutableMethodImplementation(old);
        List<BuilderInstruction> list = code.getInstructions();
        String name = method.getName();
        boolean edited = false;
        if (type.equals("Lcom/oplus/ocs/camera/configure/CameraConfigure;")) {
            // Feature lookups wait on the main thread for a vendor readiness
            // callback that Ranchu never sends. The feature config itself still
            // loads; only these waits are removed.
            for (int i = 0; i + 1 < list.size(); i++) {
                if (refers(list.get(i), FieldReference.class, type, "PROJECT_FEATURES_READY_CONDITION")
                        && refers(list.get(i + 1), MethodReference.class, "Landroid/os/ConditionVariable;", "block")) {
                    code.replaceInstruction(i, new BuilderInstruction10x(Opcode.NOP));
                    code.replaceInstruction(i + 1, new BuilderInstruction10x(Opcode.NOP));
                    hit("ready"); edited = true;
                }
            }
        }
        if (type.equals(APS + "config/AlgoSwitchConfig;") && method.getParameterTypes().isEmpty()
                && (name.equals("getApsMode") || name.equals("getSupportApsCapture"))) {
            // APS mode 4 selects NoneApsImpl, the SDK's software path, instead
            // of the vendor algorithm libraries. Do not advertise ISP capture
            // either, or snapshots wait for vendor results.
            code = new MutableMethodImplementation(1);
            code.addInstruction(new BuilderInstruction11n(Opcode.CONST_4, 0, name.equals("getApsMode") ? 4 : 0));
            code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 0));
            hit("aps_mode");
            return code;
        }
        if (type.equals(INFO + "CameraCharacteristicsHelper;") && name.equals("initialize")) {
            // The camera type comes from a vendor tag Ranchu does not report.
            // Use the camera ID instead: 0 is rear_main and 1 is front_main.
            for (int i = 0; i + 7 < list.size(); i++) {
                if (!refers(list.get(i), FieldReference.class, INFO + "CameraCharacteristicsWrapper;", "KEY_CUSTOM_CAMERA_TYPE")) continue;
                // get, move-result-object, check-cast, const/4 -1, if-eqz, aget, goto
                if (list.get(i + 5).getOpcode() != Opcode.IF_EQZ || list.get(i + 6).getOpcode() != Opcode.AGET
                        || list.get(i + 7).getOpcode() != Opcode.GOTO)
                    throw new IllegalStateException("Unexpected camera type lookup");
                int id = -1;
                for (int j = i - 1; j > i - 6; j--)
                    if (refers(list.get(j), MethodReference.class, "Ljava/util/Map;", "put")) id = ((Instruction35c) list.get(j)).getRegisterD();
                if (id < 0) throw new IllegalStateException("No camera ID before the camera type lookup");
                int result = ((OneRegisterInstruction) list.get(i + 6)).getRegisterA();
                code.replaceInstruction(i + 5, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, id, 0, 0, 0, 0,
                    new ImmutableMethodReference("Ljava/lang/Integer;", "parseInt", Arrays.asList("Ljava/lang/String;"), "I")));
                code.replaceInstruction(i + 6, new BuilderInstruction11x(Opcode.MOVE_RESULT, result));
                hit("camera_type"); edited = true;
            }
        }
        if (type.equals(INFO + "CameraCharacteristicsWrapper;") && name.equals("get") && method.getParameterTypes().size() == 1) {
            for (int i = 0; i < list.size(); i++) {
                if (!refers(list.get(i), MethodReference.class, "Landroid/hardware/camera2/CameraCharacteristics;", "get")) continue;
                Instruction35c call = (Instruction35c) list.get(i);
                code.replaceInstruction(i, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 2, call.getRegisterC(),
                    call.getRegisterD(), 0, 0, 0, helper("getCharacteristic", "Ljava/lang/Object;",
                        "Landroid/hardware/camera2/CameraCharacteristics;", "Landroid/hardware/camera2/CameraCharacteristics$Key;")));
                hit("ae_compensation"); edited = true;
            }
        }
        if (type.equals(APS + "adapter/ApsCaptureResult;")) {
            // Optional vendor arrays that NoneApsImpl never uses. Reading a
            // missing vendor tag throws, so keep the SDK's null defaults.
            List<String> keys = Arrays.asList("KEY_SENSOR_MASK", "KEY_PREVIEW_MASTER_PIPELINE",
                "KEY_CAPTURE_MASTER_PIPELINE", "KEY_UPSCALE_INPUT_SIZE", "KEY_UPSCALE_OUTPUT_SIZE");
            for (int i = 0; i + 2 < list.size(); i++) {
                BuilderInstruction ins = list.get(i);
                if (!(ins instanceof ReferenceInstruction) || !(((ReferenceInstruction) ins).getReference() instanceof FieldReference)) continue;
                FieldReference field = (FieldReference) ((ReferenceInstruction) ins).getReference();
                if (!field.getDefiningClass().endsWith("/ApsCameraMetadataKey;") || !keys.contains(field.getName())) continue;
                if (list.get(i + 1).getOpcode() != Opcode.INVOKE_VIRTUAL || list.get(i + 2).getOpcode() != Opcode.MOVE_RESULT_OBJECT)
                    throw new IllegalStateException("Unexpected optional capture metadata read");
                code.replaceInstruction(i, new BuilderInstruction10x(Opcode.NOP));
                code.replaceInstruction(i + 1, new BuilderInstruction10x(Opcode.NOP));
                code.replaceInstruction(i + 2, new BuilderInstruction11n(Opcode.CONST_4, ((OneRegisterInstruction) list.get(i + 2)).getRegisterA(), 0));
                hit("capture_metadata"); edited = true;
            }
        }
        if (type.equals(APS + "adapter/ApsUtils;") && name.equals("getYuvDataWithoutPadding")) {
            // The OEM copier only handles the phone's plane layout.
            int registers = old.getRegisterCount();
            code = new MutableMethodImplementation(registers);
            code.addInstruction(new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, registers - 3, 3,
                helper("yuvWithoutPadding", "[B", "Landroid/media/Image;", "I", "[B")));
            code.addInstruction(new BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, 0));
            code.addInstruction(new BuilderInstruction11x(Opcode.RETURN_OBJECT, 0));
            hit("yuv");
            return code;
        }
        if (type.equals(APS + "algorithm/NoneApsImpl;") && name.equals("addFrameBuff")) {
            for (int i = 0; i < list.size(); i++) {
                if (!refers(list.get(i), MethodReference.class, APS + "adapter/ApsUtils;", "convertNV21DataToJpeg")) continue;
                Instruction35c call = (Instruction35c) list.get(i);
                code.replaceInstruction(i, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 3, call.getRegisterC(),
                    call.getRegisterD(), call.getRegisterE(), 0, 0, helper("nv21ToJpeg", "[B", "[B", "I", "I")));
                hit("jpeg_orientation"); edited = true;
            }
            // The capture parameter register is reused before the encode, so
            // hand the parameter to the helper first.
            code.addInstruction(0, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, old.getRegisterCount() - 4, 1,
                helper("beginCapture", "V", "Ljava/lang/Object;")));
        }
        if (type.equals(APS + "algorithm/NoneApsImpl;") && name.equals("addPreviewFrameBuff")) {
            for (int i = 0; i + 1 < list.size(); i++) {
                if (!refers(list.get(i), FieldReference.class, "Landroid/hardware/camera2/CaptureResult;", "LOGICAL_MULTI_CAMERA_ACTIVE_PHYSICAL_ID")) continue;
                if (!refers(list.get(i + 1), MethodReference.class, "Landroid/hardware/camera2/CaptureResult;", "get"))
                    throw new IllegalStateException("Unexpected preview camera ID lookup");
                Instruction35c get = (Instruction35c) list.get(i + 1);
                code.replaceInstruction(i, new BuilderInstruction10x(Opcode.NOP));
                code.replaceInstruction(i + 1, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, get.getRegisterC(), 0, 0, 0, 0,
                    helper("previewCameraId", "Ljava/lang/String;", "Landroid/hardware/camera2/CaptureResult;")));
                hit("preview_camera_id"); edited = true;
            }
        }
        return edited ? code : null;
    }
}
