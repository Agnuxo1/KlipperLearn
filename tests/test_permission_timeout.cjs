const assert=require('node:assert/strict');
const {withPermissionTimeout,createTrialTelemetry}=require('../src/klipperlearn/mobile_app/trial-telemetry.js');
(async()=>{
 let finish,stopped=0;
 const pending=new Promise(resolve=>{finish=resolve;});
 await assert.rejects(withPermissionTimeout(pending,stream=>stream.getTracks().forEach(t=>t.stop()),10),{name:'TimeoutError'});
 finish({getTracks:()=>[{stop:()=>stopped++}]});
 await new Promise(resolve=>setTimeout(resolve,0)); assert.equal(stopped,1);
 const asked=[];let resolveMotion;
 const environment={isSecureContext:true,addEventListener(){},removeEventListener(){},AudioContext:class {},
   DeviceMotionEvent:{requestPermission(){asked.push('motion');return new Promise(resolve=>{resolveMotion=resolve;});}},
   DeviceOrientationEvent:{requestPermission(){asked.push('orientation');return Promise.resolve('granted');}}};
 const collector=createTrialTelemetry({trialId:'test-permissions',environment,mediaDevices:{getUserMedia(){asked.push('audio');return Promise.reject(Error('denied'));}}});
 const result=collector.requestPermissions({motion:true,orientation:true,audio:true});
 assert.deepEqual(asked,['motion','orientation','audio'],'Requests must start within the same gesture');
 resolveMotion('granted');const report=await result;
 assert.equal(report.permissions.motion.granted,true);assert.equal(report.permissions.audio.granted,false);
 await collector.stop();console.log('permission timeout/concurrent gesture/late stream cleanup: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
