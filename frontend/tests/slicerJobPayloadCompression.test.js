import test from "node:test";
import assert from "node:assert/strict";
import { gunzipSync } from "node:zlib";
import { apiFetch } from "../src/api.js";

test("large native painted slice payload uses lossless gzip on wire", async()=>{
  const originalFetch = globalThis.fetch;
  const originalDocument = globalThis.document;
  const originalCompression = globalThis.CompressionStream;
  try {
    globalThis.document={cookie:"csrftoken=not-a-secret-test-token"};
    const patch={face:12,polygon:[
      [12.12345678912345,0,0],[15.23456789123456,0,0],[13.34567891234567,1,0],
    ]};
    const payload={settings:{plate_objects:[{support_paint:{
      version:2,signature:"200000:abc123",regions:[
        {slot:0,patches:Array.from({length:6000},()=>patch)},
      ],
    }}]}};
    let request;
    globalThis.fetch=async(_url,init)=>{
      request=init;
      return {ok:true,json:async()=>({job:{id:"test"}})};
    };
    const result=await apiFetch("/api/printing/slicer/jobs/",{
      method:"POST",body:payload,compressJson:true,
    });
    assert.equal(result.job.id,"test");
    assert.equal(request.headers.get("Content-Encoding"),"gzip");
    assert.equal(request.headers.get("X-CSRFToken"),"not-a-secret-test-token");
    const decoded=JSON.parse(gunzipSync(Buffer.from(request.body)).toString("utf8"));
    assert.deepEqual(decoded,payload);
  } finally {
    globalThis.fetch=originalFetch;
    globalThis.document=originalDocument;
    globalThis.CompressionStream=originalCompression;
  }
});

test("small ordinary JSON requests stay backward-compatible",async()=>{
  const prevFetch=globalThis.fetch,prevDoc=globalThis.document;
  try {
    globalThis.document={cookie:""};
    let options;
    globalThis.fetch=async(_url,arg)=>{
      options=arg;
      return {ok:true,json:async()=>({ok:true})};
    };
    await apiFetch("/api/printing/slicer/jobs/",{
      method:"POST",body:{a:1},compressJson:true,
    });
    assert.equal(options.headers.get("Content-Encoding"),null);
    assert.deepEqual(JSON.parse(options.body),{a:1});
  }finally{
    globalThis.fetch=prevFetch;
    globalThis.document=prevDoc;
  }
});
