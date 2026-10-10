package android.media;
// Device test of the actual patched OEM DEX, using deterministic plane data.
// Unsafe creates only these fake Images; no HAL buffers or private Image
// constructors are needed. The patched copier reads their public methods.
import android.media.Image;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.lang.reflect.Method;
public class CameraYuvTest {
 static class P extends Image.Plane {
  ByteBuffer b; int row,pixel;
  
  public ByteBuffer getBuffer(){return b;}
  public int getRowStride(){return row;}
  public int getPixelStride(){return pixel;}
 }
 static class I extends Image {
  P[] planes;
  
  public int getFormat(){return 35;}
  public int getWidth(){return 4;}
  public int getHeight(){return 4;}
  public long getTimestamp(){return 0;}
  public void setTimestamp(long t){}
  public Plane[] getPlanes(){return planes;}
  public void close(){}
 }
 static Object alloc(Class<?> c)throws Exception {
  Class<?> u=Class.forName("sun.misc.Unsafe"); java.lang.reflect.Field f=u.getDeclaredField("theUnsafe"); f.setAccessible(true); return u.getMethod("allocateInstance",Class.class).invoke(f.get(null),c);
 }
 static P p(byte[] data,int r,int pixel)throws Exception {P p=(P)alloc(P.class);p.b=ByteBuffer.wrap(data);p.row=r;p.pixel=pixel;return p;}
 static I i(P... planes)throws Exception {I i=(I)alloc(I.class);i.planes=planes;return i;}
 public static void main(String[] args)throws Exception {
  Method m=Class.forName("com.oplus.ocs.camera.consumer.apsAdapter.adapter.ApsUtils").getMethod("getYuvDataWithoutPadding",Image.class,int.class,byte[].class);
  byte[] y={1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
  byte[] expected={1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,51,31,52,32,53,33,54,34};
  I[] images={
   i(p(y,4,1),p(new byte[]{31,32,33,34},2,1),p(new byte[]{51,52,53,54},2,1)),
   i(p(new byte[]{1,2,3,4,99,99,5,6,7,8,99,99,9,10,11,12,99,99,13,14,15,16},6,1),p(new byte[]{31,32,99,33,34},3,1),p(new byte[]{51,52,99,53,54},3,1)),
   i(p(y,4,1),p(new byte[]{31,51,32,52,33,53,34},4,2),p(new byte[]{51,32,52,33,53,34,54},4,2)),
   i(p(y,4,1),p(new byte[]{31,52,32,53,33,54,34},4,2),p(new byte[]{51,31,52,32,53,33,54},4,2)),
   i(p(y,4,1),p(new byte[]{31,99,32,99,99,99,33,99,34},6,2),p(new byte[]{51,99,52,99,99,99,53,99,54},6,2))
  };
  for(int i=0;i<images.length;i++){
   byte[] actual=(byte[])m.invoke(null,images[i],17,null);
   if(!Arrays.equals(expected,actual))throw new AssertionError(i+" "+Arrays.toString(actual));
   byte[] reuse=new byte[24];
   if(m.invoke(null,images[i],17,reuse)!=reuse||!Arrays.equals(reuse,expected))throw new AssertionError("reuse "+i);
   for(P p:images[i].planes)if(p.b.position()!=0)throw new AssertionError("buffer consumed");
  }
  Method encoder=m.getDeclaringClass().getMethod("convertNV21DataToJpeg",byte[].class,int.class,int.class);
  int[] orientations={1,6,3,8};
  for(int i=0;i<4;i++){
   byte[] jpeg=(byte[])encoder.invoke(null,expected,4|((i*90)<<16),4);
   ExifInterface exif=new ExifInterface(new java.io.ByteArrayInputStream(jpeg));
   if(exif.getAttributeInt(ExifInterface.TAG_ORIENTATION,0)!=orientations[i])throw new AssertionError("EXIF rotation "+i);
  }
  System.out.println("PASS: five plane layouts, array reuse, buffer positions, EXIF rotations 0/90/180/270");
 }
}
