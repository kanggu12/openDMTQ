// Exercises the arm32 JNI bridge from ART: native methods implemented in a 32-bit library,
// called from Java with every kind of argument, calling back into Java.
//
//   app_process -cp test.dex /system/bin Arm32JniTest <folder with libarm32.so and libjnitest.so>
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.Arrays;

public class Arm32JniTest {
    static int failures = 0;

    static void check(String name, boolean ok) {
        System.out.println((ok ? "ok   " : "FAIL ") + name);
        if (!ok) failures++;
    }

    // Implemented in the 32-bit library.
    static native int add(int a, int b);
    static native long mix(int a, long b, int c, double d, float e, long f, byte g, short h, char i, boolean j);
    static native double average(double[] values);
    static native String greet(String name);
    native int instanceSum(int extra);
    static native int callbacks();
    static native int[] reverse(int[] in);
    static native void fill(ByteBuffer direct, byte value);
    static native ByteBuffer wrap();
    static native void raise(String message);
    static native Object echo(Object o);
    static native int threads(int n);
    static native int gl();
    static native int audio(int callbacks);
    static native void prepareSignal();
    static native int signalPrepared(int tid);
    static native int stackCheck();
    static native int localSymbols(String plugin);
    static native int frameProbe();
    static native void fillFloats(FloatBuffer b, float v);
    static native int heapInUse();
    // Not registered: the VM finds these by their Java_ names.
    static native int byName(int v);
    static native int over(int v);
    static native int over(String s);

    // Called from the 32-bit library.
    int base = 40;
    int twice(int v) { return v * 2; }
    static long staticMix(int a, long b, float c, double d, String s) { return a + b + (long) c + (long) d + s.length(); }
    static String concat(String a, String b) { return a + b; }
    static int counter = 0;
    static synchronized void bump() { counter++; }

    public static void main(String[] args) {
        System.load(args[0] + "/libarm32.so");
        System.load(args[0] + "/libjnitest.so");
        check("int arguments", add(2, 3) == 5);
        long want = 1 + (2L << 33) + 3 + (long) 4.5 + (long) 5.25f + (-6L) + (-7) + (-8) + 'A' + 1;
        check("ten mixed arguments", mix(1, 2L << 33, 3, 4.5, 5.25f, -6L, (byte) -7, (short) -8, 'A', true) == want);
        check("double array elements and double result", average(new double[] {1, 2, 3, 4.5}) == 2.625);
        check("strings both ways", "hello S26 from arm32".equals(greet("S26")));
        Arm32JniTest t = new Arm32JniTest();
        check("fields and an instance callback", t.instanceSum(2) == 84 && t.base == 41);
        check("callbacks with ..., va_list and jvalue[] arguments", callbacks() == 4);
        check("int array regions and elements", Arrays.equals(reverse(new int[] {1, 2, 3, 4, 5}), new int[] {5, 4, 3, 2, 1}));
        ByteBuffer b = ByteBuffer.allocateDirect(64);
        fill(b, (byte) 0x5a);
        boolean all = true;
        for (int i = 0; i < 64; i++) all &= b.get(i) == 0x5a;
        check("Java direct buffer written by 32-bit code", all);
        ByteBuffer w = wrap();
        check("direct buffer over 32-bit memory", w.capacity() == 16 && w.get(0) == 1 && w.get(15) == 16);
        boolean thrown = false;
        try {
            raise("boom");
        } catch (IllegalStateException e) {
            thrown = "boom".equals(e.getMessage());
        }
        check("exception thrown from 32-bit code", thrown);
        Object o = new Object();
        check("references round trip", echo(o) == o);
        counter = 0;
        threads(4);
        check("four 32-bit threads attach and call Java", counter == 400);
        int g = gl();
        check("EGL and OpenGL ES from 32-bit code (" + g + "/8191)", g == 8191);
        int a = audio(20);
        check("OpenSL ES buffer queue callbacks on the audio thread (" + a + ")", a >= 20);
        // A second engine and player after the first were destroyed: interfaces of destroyed
        // objects must not be taken for the new ones.
        a = audio(10);
        check("OpenSL ES again after Destroy (" + a + ")", a >= 10);
        // This is the process's main thread (its thread id is the process id), as an app's UI
        // thread is: pthread_getattr_np must describe its own stack, which the garbage collector
        // scans from the stack pointer up to the top it reports.
        int s = stackCheck();
        check("pthread_getattr_np on the main thread gives its own stack (" + s + ")", s == 1);
        // A library loaded later binds nothing of this one's (Android 6's linker keeps
        // System.loadLibrary's libraries out of other libraries' symbol lookups).
        int l = localSymbols(args[0] + "/libplugin.so");
        check("a later library does not bind to this library's symbols (" + l + ")", l == 1);
        // A native method that returns with a local frame still pushed: the VM ends the frame
        // with the call, and the next call starts with the same local references as the first.
        int f1 = frameProbe(), f2 = frameProbe(), f3 = frameProbe();
        check("local frames left open end with the native call (" + Integer.toHexString(f1) + " " + Integer.toHexString(f2) + " "
                + Integer.toHexString(f3) + ")", f1 == f2 && f2 == f3);
        check("native methods found by name, overloads included", byName(41) == 42 && over(21) == 42 && over("abc") == 3);
        prepareSignal();
        final int myTid = android.os.Process.myTid();
        final int[] result = new int[1];
        Thread sender = new Thread(() -> result[0] = signalPrepared(myTid));
        sender.start();
        try {
            sender.join();
        } catch (InterruptedException e) {
            result[0] = -100;
        }
        check("signal and restart for a thread waiting in Java (" + result[0] + ")", result[0] == 1);
        // Java threads that call native code once and end, as audio, video and pool threads do over
        // a game session: each gets a guest thread, which must end with it. Left behind, each would
        // keep one of the runtime's 256 processor slots and an 8 MB guest stack for good.
        int churned = 0;
        for (int i = 0; i < 300; i++) {
            final int v = i;
            final int[] out = new int[1];
            Thread th = new Thread(() -> out[0] = add(v, 1));
            th.start();
            try {
                th.join();
            } catch (InterruptedException e) {
                break;
            }
            if (out[0] == v + 1) churned++;
        }
        check("300 short-lived Java threads call native code (" + churned + ")", churned == 300);
        // Each thread hands a native method a direct buffer of its own, as Unity's web requests
        // do: the guest copy of the buffer must go with the thread, not stay in the guest heap.
        int heapBefore = heapInUse();
        for (int i = 0; i < 32; i++) {
            Thread th = new Thread(() -> fill(ByteBuffer.allocateDirect(256 << 10), (byte) 1));
            th.start();
            try {
                th.join();
            } catch (InterruptedException e) {
                break;
            }
        }
        int grown = heapInUse() - heapBefore;
        check("direct buffer copies end with their threads (" + (grown >> 10) + " KB left)", grown < (2 << 20));
        // A float view of a direct buffer: its capacity counts floats, the copy must cover bytes.
        // (Last: before the fix the guest wrote past its copy into the guest heap.)
        FloatBuffer fb = ByteBuffer.allocateDirect(64).order(ByteOrder.nativeOrder()).asFloatBuffer();
        fillFloats(fb, 2.5f);
        boolean floats = fb.capacity() == 16;
        for (int i = 0; i < 16; i++) floats &= fb.get(i) == 2.5f;
        check("direct float buffer copied whole", floats);
        System.out.println(failures == 0 ? "ALL CHECKS PASSED" : "SOME CHECKS FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }
}
