// SPDX-License-Identifier: MIT
// Node75 LP 2.4G Boot-interface LED controller. Never sends keyboard input.
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <IOKit/hid/IOHIDLib.h>
#include <IOKit/hidsystem/IOHIDLib.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop_requested=0;
static void stop(int sig){(void)sig;stop_requested=1;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static long prop(IOHIDDeviceRef d,CFStringRef k){
    CFTypeRef v=IOHIDDeviceGetProperty(d,k);long n=-1;
    if(v&&CFGetTypeID(v)==CFNumberGetTypeID())CFNumberGetValue(v,kCFNumberLongType,&n);
    return n;
}
static bool led_cache(IOHIDDeviceRef d,unsigned char *mask){
    CFArrayRef es=IOHIDDeviceCopyMatchingElements(d,NULL,0);if(!es)return false;
    unsigned found=0;*mask=0;
    for(CFIndex i=0;i<CFArrayGetCount(es);i++){
        IOHIDElementRef e=(IOHIDElementRef)CFArrayGetValueAtIndex(es,i);unsigned u=IOHIDElementGetUsage(e);
        if(IOHIDElementGetType(e)!=kIOHIDElementTypeOutput||IOHIDElementGetUsagePage(e)!=8||u<1||u>3||
           IOHIDElementGetReportID(e)!=0||IOHIDElementGetReportSize(e)!=1)continue;
        IOHIDValueRef v=NULL;
        if(IOHIDDeviceGetValue(d,e,&v)!=kIOReturnSuccess||!v)continue;
        if(IOHIDValueGetIntegerValue(v))*mask|=(unsigned char)(1u<<(u-1));
        found|=1u<<(u-1);
    }
    CFRelease(es);return found==7;
}
static IOHIDDeviceRef connect_receiver(IOHIDManagerRef m){
    CFSetRef ds=IOHIDManagerCopyDevices(m);if(!ds)return NULL;
    CFIndex n=CFSetGetCount(ds);IOHIDDeviceRef devices[n],result=NULL;CFSetGetValues(ds,(const void**)devices);
    for(CFIndex i=0;i<n;i++){
        IOHIDDeviceRef d=devices[i];
        if(prop(d,CFSTR(kIOHIDPrimaryUsagePageKey))==1&&prop(d,CFSTR(kIOHIDPrimaryUsageKey))==6&&
           prop(d,CFSTR(kIOHIDMaxInputReportSizeKey))==8&&prop(d,CFSTR(kIOHIDMaxOutputReportSizeKey))==1){
            IOReturn opened=IOHIDDeviceOpen(d,0);
            if(opened!=kIOReturnSuccess){printf("ERROR receiver open %08x; input-monitoring access %d\n",opened,IOHIDCheckAccess(kIOHIDRequestTypeListenEvent));continue;}
            unsigned char mask;
            if(led_cache(d,&mask)){result=(IOHIDDeviceRef)CFRetain(d);break;}
            puts("ERROR cannot read host LED cache");
            IOHIDDeviceClose(d,0);
        }
    }
    CFRelease(ds);return result;
}
static unsigned char host_leds(IOHIDDeviceRef d){
    unsigned char mask=0;led_cache(d,&mask);
    CGEventFlags flags=CGEventSourceFlagsState(kCGEventSourceStateCombinedSessionState);
    return (mask&~2u)|((flags&kCGEventFlagMaskAlphaShift)?2:0);
}
static bool send_led(IOHIDDeviceRef d,unsigned char mask){
    IOReturn r=IOHIDDeviceSetReport(d,kIOHIDReportTypeOutput,0,&mask,1);
    if(r!=kIOReturnSuccess)printf("ERROR HID %08x\n",r);
    return r==kIOReturnSuccess;
}
static void disconnect(IOHIDDeviceRef *d){
    if(*d){IOHIDDeviceClose(*d,0);CFRelease(*d);*d=NULL;}
}
int main(int argc,char **argv){
    if(argc==2&&!strcmp(argv[1],"--check-access")){printf("%d\n",IOHIDCheckAccess(kIOHIDRequestTypeListenEvent));return 0;}
    if(argc!=1)return 64;
    signal(SIGINT,stop);signal(SIGTERM,stop);signal(SIGPIPE,SIG_IGN);setvbuf(stdout,NULL,_IOLBF,0);
    IOHIDManagerRef manager=IOHIDManagerCreate(NULL,0);int vid=0x19f5,pid=0x2620;
    CFNumberRef v=CFNumberCreate(NULL,kCFNumberIntType,&vid),p=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    const void *ks[]={CFSTR(kIOHIDVendorIDKey),CFSTR(kIOHIDProductIDKey)},*vs[]={v,p};
    CFDictionaryRef match=CFDictionaryCreate(NULL,ks,vs,2,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    IOHIDManagerSetDeviceMatching(manager,match);IOReturn opened=IOHIDManagerOpen(manager,0);
    printf("ACCESS input-monitoring %d; manager open %08x\n",IOHIDCheckAccess(kIOHIDRequestTypeListenEvent),opened);
    IOHIDManagerScheduleWithRunLoop(manager,CFRunLoopGetCurrent(),kCFRunLoopDefaultMode);
    IOHIDDeviceRef device=NULL;char state[32]="idle",buffer[128];size_t used=0;
    double phase=now(),retry=0,last_write=0;int last_mask=-1;bool acquired=false;
    puts("READY");
    while(!stop_requested){
        fd_set readfds;FD_ZERO(&readfds);FD_SET(STDIN_FILENO,&readfds);struct timeval wait={0,50000};
        int ready=select(STDIN_FILENO+1,&readfds,NULL,NULL,&wait);
        if(ready>0){
            char ch;ssize_t count=read(STDIN_FILENO,&ch,1);if(count<=0)break;
            if(ch=='\n'){
                buffer[used]=0;used=0;
                if(!strcmp(buffer,"quit"))break;
                if(!strcmp(buffer,"idle")||!strcmp(buffer,"running")||!strcmp(buffer,"attention")||!strcmp(buffer,"completed")){
                    snprintf(state,sizeof(state),"%s",buffer);phase=now();last_mask=-1;printf("STATE %s\n",state);
                }
            }else if(used<sizeof(buffer)-1)buffer[used++]=ch;else{used=0;puts("ERROR oversized command");}
        }
        CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.001,false);double t=now();
        bool active=strcmp(state,"idle")!=0;
        if(!active){
            if(device&&acquired){bool restored=send_led(device,host_leds(device));puts(restored?"RESTORED":"ERROR restore");acquired=false;disconnect(&device);last_mask=-1;}
            continue;
        }
        if(!device&&t>=retry){
            device=connect_receiver(manager);retry=t+2;
            if(device){puts("CONNECTED boot 19f5:2620");last_mask=-1;}
            else puts("ERROR receiver unavailable; retrying");
        }
        if(!device)continue;
        bool on=!strcmp(state,"completed")||
            (!strcmp(state,"running")&&((int)((t-phase)/0.8)%2==0))||
            (!strcmp(state,"attention")&&((int)((t-phase)/0.2)%2==0));
        unsigned char mask=(host_leds(device)&~2u)|(on?2:0);
        if(mask!=last_mask||t-last_write>=2){
            if(!send_led(device,mask)){disconnect(&device);acquired=false;last_mask=-1;retry=t+2;continue;}
            acquired=true;last_mask=mask;last_write=t;
        }
    }
    if(device&&acquired)puts(send_led(device,host_leds(device))?"RESTORED":"ERROR restore");
    disconnect(&device);IOHIDManagerUnscheduleFromRunLoop(manager,CFRunLoopGetCurrent(),kCFRunLoopDefaultMode);
    IOHIDManagerClose(manager,0);CFRelease(manager);CFRelease(match);CFRelease(v);CFRelease(p);return 0;
}
