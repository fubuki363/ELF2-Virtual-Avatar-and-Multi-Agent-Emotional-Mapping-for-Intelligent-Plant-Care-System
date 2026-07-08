import serial, time

s = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
time.sleep(0.5)
END = b'\xff\xff\xff'

def f(x,y,w,h,c):
    s.write(f'fill {x},{y},{w},{h},{c}'.encode('ascii') + END)
    time.sleep(0.12)

G=2016; C=2047; B=0; DG=4256

print("BOOT START"); f(0,0,320,240,B); time.sleep(0.4)

for t in [15, 45]:
    f(0,0,t,2,C);f(0,0,2,t,C);f(320-t,0,t,2,C);f(318,0,2,t,C)
    f(0,238,t,2,C);f(0,240-t,2,t,C);f(320-t,238,t,2,C);f(318,240-t,2,t,C)
    time.sleep(0.3)

f(0,0,320,2,G);time.sleep(0.15);f(0,0,2,240,G);time.sleep(0.15)
f(318,0,2,240,G);time.sleep(0.15);f(0,238,320,2,G);time.sleep(0.3)
f(6,6,308,1,DG);time.sleep(0.15);f(6,6,1,228,DG);time.sleep(0.15)
f(313,6,1,228,DG);time.sleep(0.15);f(6,233,308,1,DG);time.sleep(0.3)

f(14,14,160,14,DG);f(14,14,160,2,G);time.sleep(0.5)
f(10,38,300,2,C);time.sleep(0.4)
f(30,55,260,8,C);time.sleep(0.3);f(30,75,260,4,G);time.sleep(0.3)
f(30,90,260,8,C);time.sleep(0.4)

bx,by,bw,bh=28,185,264,8;f(bx,by,bw,bh,DG);time.sleep(0.3)
for pct in [20,40,55,70,85,100]:
    f(bx,by,int(bw*pct/100),bh,C);time.sleep(0.6)

f(10,205,300,1,DG);time.sleep(0.2);f(14,212,200,1,G);time.sleep(0.3)

for _ in range(3):
    f(85,148,150,22,C);time.sleep(0.4);f(85,148,150,22,B);time.sleep(0.4)
f(85,148,150,22,C);time.sleep(2)

f(0,0,320,240,B);time.sleep(0.3)
f(6,6,308,1,G);time.sleep(0.15);f(6,6,1,228,G);time.sleep(0.15)
f(313,6,1,228,G);time.sleep(0.15);f(6,233,308,1,G);time.sleep(0.15)
f(14,16,4,10,C)

s.close();print("DONE")
