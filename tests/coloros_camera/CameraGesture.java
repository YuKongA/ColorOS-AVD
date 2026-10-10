import android.view.InputEvent;
import android.view.MotionEvent;
import android.os.SystemClock;
import java.lang.reflect.Method;
/** Shell-only two-finger injection; PASS confirms input delivery, not camera zoom. */
public class CameraGesture {
    private static Object manager;
    private static Method inject;
    private static long down;
    private static void send(int action, float x1, float y1, float x2, float y2, int n) throws Exception {
        MotionEvent.PointerProperties[] p=new MotionEvent.PointerProperties[n];
        MotionEvent.PointerCoords[] c=new MotionEvent.PointerCoords[n];
        for(int i=0;i<n;i++) {
            p[i]=new MotionEvent.PointerProperties();p[i].id=i;p[i].toolType=MotionEvent.TOOL_TYPE_FINGER;
            c[i]=new MotionEvent.PointerCoords();c[i].x=i==0?x1:x2;c[i].y=i==0?y1:y2;c[i].pressure=1;c[i].size=1;
        }
        MotionEvent e=MotionEvent.obtain(down,SystemClock.uptimeMillis(),action,n,p,c,0,0,1,1,0,0,4098,0);
        if(!Boolean.TRUE.equals(inject.invoke(manager,e,2))) throw new IllegalStateException("Injection failed");
        e.recycle();
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("Usage: CameraGesture centerX centerY startRadius endRadius");
        Class<?> cls=Class.forName("android.hardware.input.InputManagerGlobal");
        manager=cls.getMethod("getInstance").invoke(null);
        inject=cls.getMethod("injectInputEvent",InputEvent.class,int.class);
        float cx=Float.parseFloat(args[0]),cy=Float.parseFloat(args[1]),start=Float.parseFloat(args[2]),end=Float.parseFloat(args[3]);
        down=SystemClock.uptimeMillis();
        send(0,cx-start,cy,cx+start,cy,1);
        send(5|(1<<8),cx-start,cy,cx+start,cy,2);
        for(int i=1;i<=20;i++) {
            float r=start+(end-start)*i/20;
            send(2,cx-r,cy,cx+r,cy,2);SystemClock.sleep(40);
        }
        send(6|(1<<8),cx-end,cy,cx+end,cy,2);
        send(1,cx-end,cy,cx+end,cy,1);
        System.out.println("PASS: injected two-finger gesture");
    }
}
