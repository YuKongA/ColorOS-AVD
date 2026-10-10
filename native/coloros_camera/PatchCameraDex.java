import java.util.*;
import com.android.tools.smali.dexlib2.*;
import com.android.tools.smali.dexlib2.iface.*;
import com.android.tools.smali.dexlib2.iface.instruction.*;
import com.android.tools.smali.dexlib2.iface.instruction.formats.Instruction35c;
import com.android.tools.smali.dexlib2.iface.instruction.formats.Instruction12x;
import com.android.tools.smali.dexlib2.iface.reference.*;
import com.android.tools.smali.dexlib2.immutable.*;
import com.android.tools.smali.dexlib2.immutable.reference.*;
import com.android.tools.smali.dexlib2.builder.*;
import com.android.tools.smali.dexlib2.builder.instruction.*;
import com.android.tools.smali.dexlib2.writer.pool.*;

public final class PatchCameraDex {
    private static final String HELPER = "Lcom/coloros/avd/camera/VirtualCameraBuffers;";
    public static void main(String[] args) throws Exception {
        DexFile source = DexFileFactory.loadDexFile(args[0], Opcodes.forApi(28));
        DexPool pool = new DexPool(Opcodes.forApi(28));
        int changed = 0;
        for (ClassDef cls : source.getClasses()) {
            List<Method> methods = new ArrayList<>();
            for (Method method : cls.getMethods()) {
                MethodImplementation old = method.getImplementation();
                if (old == null) { methods.add(method); continue; }
                MutableMethodImplementation code = new MutableMethodImplementation(old);
                boolean edited = false;
                if ((cls.getType().equals("Lim/c1;") || cls.getType().equals("Lrm/q0;"))
                        && method.getName().equals("vf") && method.getReturnType().equals("Z")
                        && method.getParameterTypes().equals(Arrays.asList("Ljava/lang/String;"))) {
                    if (old.getRegisterCount() < 3 || old.getRegisterCount() > 17)
                        throw new IllegalStateException("Unsupported capture stream registers");
                    Label original = code.getInstructions().get(0).getLocation().addNewLabel();
                    MethodReference stream = new ImmutableMethodReference(HELPER, "captureStreamOverride", Arrays.asList("Ljava/lang/String;"), "I");
                    code.addInstruction(0, new BuilderInstruction22c(Opcode.IGET_BOOLEAN, 0,
                        old.getRegisterCount() - 2, new ImmutableFieldReference("Lcom/oplus/camera/module/BaseMode;", "C0", "Z")));
                    code.addInstruction(1, new BuilderInstruction21t(Opcode.IF_NEZ, 0, original));
                    code.addInstruction(2, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, old.getRegisterCount() - 1, 1, stream));
                    code.addInstruction(3, new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
                    code.addInstruction(4, new BuilderInstruction22b(Opcode.ADD_INT_LIT8, 0, 0, 1));
                    code.addInstruction(5, new BuilderInstruction21t(Opcode.IF_EQZ, 0, original));
                    code.addInstruction(6, new BuilderInstruction22b(Opcode.ADD_INT_LIT8, 0, 0, -1));
                    code.addInstruction(7, new BuilderInstruction11x(Opcode.RETURN, 0));
                    edited = true; changed++;
                }
                if (cls.getType().equals("Lcb/g1;") && (method.getName().equals("r") || method.getName().equals("w"))
                        && method.getReturnType().equals("F") && method.getParameterTypes().equals(Arrays.asList("Ldb/c;"))) {
                    // The OEM limits depend on SAT/telephoto tags. Ranchu uses
                    // one sensor per facing and Camera2's real digital range.
                    code = new MutableMethodImplementation(3);
                    if (method.getName().equals("r")) {
                        code.addInstruction(new BuilderInstruction22c(Opcode.IGET_OBJECT, 0, 1,
                            new ImmutableFieldReference(cls.getType(), "a", "Lcom/oplus/ocs/camera/CameraDeviceInfo;")));
                        MethodReference maximum = new ImmutableMethodReference(HELPER, "maxDigitalZoom", Arrays.asList("Ljava/lang/Object;"), "F");
                        code.addInstruction(new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 0, 0, 0, 0, 0, maximum));
                        code.addInstruction(new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
                    } else {
                        code.addInstruction(new BuilderInstruction31i(Opcode.CONST, 0, 0x3f800000));
                    }
                    code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 0));
                    edited = true; changed++;
                }
                if (cls.getType().equals("Lil/f;") && method.getName().equals("g")
                        && method.getReturnType().equals("F")
                        && method.getParameterTypes().equals(Arrays.asList("F"))) {
                    // OEM discrete focal points can represent switching to a
                    // telephoto sensor at 1x. Ranchu has one rear sensor, so
                    // the displayed ratio must map directly to digital zoom.
                    code = new MutableMethodImplementation(2);
                    MethodReference clamp = new ImmutableMethodReference(HELPER, "digitalZoom",
                        Arrays.asList("F"), "F");
                    code.addInstruction(new BuilderInstruction35c(Opcode.INVOKE_STATIC, 1, 1, 0, 0, 0, 0, clamp));
                    code.addInstruction(new BuilderInstruction11x(Opcode.MOVE_RESULT, 1));
                    code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 1));
                    edited = true; changed++;
                }
                if (cls.getType().equals("Lpp/e;") && method.getName().equals("p")
                        && method.getReturnType().equals("Ljava/util/ArrayList;")
                        && method.getParameterTypes().equals(Arrays.asList("Ljava/lang/String;", "Z", "Z"))) {
                    // Filter the source of headline/panel/edit lists, including
                    // portrait rows cached by older APKs in mode_data.db.
                    int found = 0;
                    for (int i = 0; i < code.getInstructions().size(); i++) {
                        BuilderInstruction ins = code.getInstructions().get(i);
                        if (!(ins instanceof ReferenceInstruction)) continue;
                        Reference ref = ((ReferenceInstruction)ins).getReference();
                        if (!(ref instanceof StringReference)) continue;
                        String sql = ((StringReference)ref).getString();
                        if (!sql.startsWith("select * from mode_info where position = ?")) continue;
                        String replacement = sql.replace("position = ?", "position = ? and mode_name != 'portrait'");
                        code.replaceInstruction(i, new BuilderInstruction21c(Opcode.CONST_STRING,
                            ((OneRegisterInstruction)ins).getRegisterA(), new ImmutableStringReference(replacement)));
                        found++;
                    }
                    if (found != 2) throw new IllegalStateException("Unexpected mode list queries: " + found);
                    edited = true; changed++;
                }
                if (cls.getType().equals("Lim/c1;") && method.getName().equals("dg")
                        && method.getParameterTypes().equals(Arrays.asList("Lcom/oplus/camera/protocal/event/message/deviceProtocol/deviceControlRequest/EventMessageCaptureRequestStage;"))) {
                    // NoneApsImpl has no vendor DecisionResult; the ordinary
                    // BaseMode capture stage remains the authoritative gate.
                    code = new MutableMethodImplementation(2);
                    MethodReference base = new ImmutableMethodReference(cls.getSuperclass(), method.getName(),
                        method.getParameterTypes(), method.getReturnType());
                    code.addInstruction(new BuilderInstruction3rc(Opcode.INVOKE_SUPER_RANGE, 0, 2, base));
                    code.addInstruction(new BuilderInstruction10x(Opcode.RETURN_VOID));
                    edited = true; changed++;
                }
                if (method.getName().equals("getSupportFunction") && method.getReturnType().equals("Z")
                        && method.getParameterTypes().equals(Arrays.asList("Ljava/lang/String;"))
                        && (cls.getType().startsWith("Lim/") || cls.getType().startsWith("Lrm/")
                            || cls.getType().startsWith("Lsm/") || cls.getType().equals("Lgm/q2;")
                            || cls.getType().equals("Lgm/e3;")
                            || cls.getType().equals("Lcom/oplus/camera/module/BaseMode;")
                            || cls.getType().equals("Lcom/oplus/camera/module/a;"))) {
                    if (old.getRegisterCount() < 4) throw new IllegalStateException("No feature override scratch registers");
                    Label original = code.getInstructions().get(0).getLocation().addNewLabel();
                    MethodReference override = new ImmutableMethodReference(HELPER, "featureOverride", Arrays.asList("Ljava/lang/String;"), "I");
                    code.addInstruction(0, new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, old.getRegisterCount() - 1, 1, override));
                    code.addInstruction(1, new BuilderInstruction11x(Opcode.MOVE_RESULT, 0));
                    code.addInstruction(2, new BuilderInstruction11n(Opcode.CONST_4, 1, -1));
                    code.addInstruction(3, new BuilderInstruction22t(Opcode.IF_EQ, 0, 1, original));
                    code.addInstruction(4, new BuilderInstruction11x(Opcode.RETURN, 0));
                    edited = true; changed++;
                }
                if (cls.getType().equals("Lpe/f;") && method.getName().equals("canProcess")
                        && method.getParameterTypes().isEmpty() && method.getReturnType().equals("Z")) {
                    // The OEM beauty engine can report success with an empty
                    // texture on Ranchu. Use the renderer's existing bypass.
                    code = new MutableMethodImplementation(old.getRegisterCount());
                    code.addInstruction(new BuilderInstruction11n(Opcode.CONST_4, 0, 0));
                    code.addInstruction(new BuilderInstruction11x(Opcode.RETURN, 0));
                    edited = true; changed++;
                }
                if (cls.getType().equals("Ldf/f0;") && method.getName().equals("e") && method.getParameterTypes().equals(Arrays.asList("Ldf/g0;", "I", "I", "F"))) {
                    int found = 0;
                    for (int i = 0; i < code.getInstructions().size(); i++) {
                        BuilderInstruction ins = code.getInstructions().get(i);
                        if (ins.getOpcode() != Opcode.FLOAT_TO_INT) continue;
                        Instruction12x convert = (Instruction12x)ins;
                        if (convert.getRegisterA() != 1 || convert.getRegisterB() != 1 || old.getRegisterCount() != 8)
                            throw new IllegalStateException("Unexpected exposure increment registers");
                        MethodReference max = new ImmutableMethodReference("Ljava/lang/Math;", "max", Arrays.asList("I", "I"), "I");
                        code.addInstruction(++i, new BuilderInstruction11n(Opcode.CONST_4, 2, 1));
                        code.addInstruction(++i, new BuilderInstruction35c(Opcode.INVOKE_STATIC, 2, 1, 2, 0, 0, 0, max));
                        code.addInstruction(++i, new BuilderInstruction11x(Opcode.MOVE_RESULT, 1));
                        found++;
                    }
                    if (found != 1) throw new IllegalStateException("Unexpected exposure increment count: " + found);
                    edited = true; changed++;
                }
                for (int i = 0; i < code.getInstructions().size(); i++) {
                    BuilderInstruction ins = code.getInstructions().get(i);
                    if (!(ins instanceof Instruction35c)) continue;
                    Instruction35c call = (Instruction35c)ins;
                    if (!(call.getReference() instanceof MethodReference)) continue;
                    MethodReference ref = (MethodReference)call.getReference();
                    String replacement = null;
                    List<String> params = new ArrayList<>();
                    for (CharSequence p : ref.getParameterTypes()) params.add(p.toString());
                    if (cls.getType().equals("Lrm/q0;") && ref.getDefiningClass().equals("Landroid/media/CamcorderProfile;") && ref.getName().equals("get") && params.equals(Arrays.asList("I","I"))) replacement="getProfile";
                    if (cls.getType().equals("Lqm/f0;") && ref.getDefiningClass().equals("Landroid/media/MediaCodec;") && ref.getName().equals("createPersistentInputSurface")) replacement="createVideoSurface";
                    if (cls.getType().equals("Lji/c;") && ref.getDefiningClass().equals("Lcom/oplus/hardware/camera2/OplusCaptureResult;") && ref.getName().equals("get")) { replacement="getOptionalMetadata"; params=Arrays.asList("Ljava/lang/Object;", "Landroid/hardware/camera2/CaptureResult$Key;"); }
                    if (cls.getType().equals("Lcom/oplus/camera/h7;") && ref.getDefiningClass().equals("Landroid/media/AudioManager;") && ref.getName().equals("getMicrophones")) { replacement="getMicrophones"; params=Arrays.asList("Landroid/media/AudioManager;"); }
                    if (cls.getType().equals("Lcom/oplus/camera/entry/CameraEntry;") && ref.getDefiningClass().equals("Landroid/content/pm/ShortcutManager;") && ref.getName().equals("addDynamicShortcuts")) { replacement="publishShortcuts"; params=Arrays.asList("Landroid/content/pm/ShortcutManager;", "Ljava/util/List;"); }
                    if (replacement == null) continue;
                    MethodReference target = new ImmutableMethodReference(HELPER,replacement,params,ref.getReturnType());
                    code.replaceInstruction(i,new BuilderInstruction35c(Opcode.INVOKE_STATIC,call.getRegisterCount(),call.getRegisterC(),call.getRegisterD(),call.getRegisterE(),call.getRegisterF(),call.getRegisterG(),target));
                    edited=true; changed++;
                }
                if (cls.getType().equals("Lli/h;") && method.getName().equals("d3") && method.getParameterTypes().equals(Arrays.asList("Landroid/media/Image;"))) {
                    MethodReference target = new ImmutableMethodReference(HELPER,"getNv21Planes",Arrays.asList("Landroid/media/Image;"),"[Landroid/media/Image$Plane;");
                    code.addInstruction(0,new BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE,old.getRegisterCount()-1,1,target));
                    edited=true; changed++;
                }
                methods.add(edited ? new ImmutableMethod(method.getDefiningClass(),method.getName(),method.getParameters(),method.getReturnType(),method.getAccessFlags(),method.getAnnotations(),method.getHiddenApiRestrictions(),code) : method);
            }
            pool.internClass(new ImmutableClassDef(cls.getType(),cls.getAccessFlags(),cls.getSuperclass(),cls.getInterfaces(),cls.getSourceFile(),cls.getAnnotations(),cls.getFields(),methods));
        }
        int expected = Integer.parseInt(args[2]);
        if (changed != expected) throw new IllegalStateException("Expected " + expected + " camera calls, found " + changed);
        if (args.length > 3) for (ClassDef cls : DexFileFactory.loadDexFile(args[3], Opcodes.forApi(35)).getClasses()) pool.internClass(cls);
        pool.writeTo(new com.android.tools.smali.dexlib2.writer.io.FileDataStore(new java.io.File(args[1])));
        System.out.println("Patched " + changed + " scoped camera calls");
    }
}
