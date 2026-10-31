"""Copy static HDR SEI payloads into HEVC key packets without re-encoding.

Handles MP4 length-prefixed HEVC only. Rejects malformed packets or missing HDR
metadata. The compressed picture data and timestamps are retained verbatim.
"""
from pathlib import Path
import av


def unpack_nals(data, length_size):
    if length_size not in (1,2,4):raise ValueError('Unsupported HEVC NAL length size')
    result=[]; pos=0
    while pos<len(data):
        if pos+length_size>len(data):raise ValueError('Truncated NAL length')
        size=int.from_bytes(data[pos:pos+length_size],'big');pos+=length_size
        if size<2 or pos+size>len(data):raise ValueError('Invalid HEVC NAL size')
        result.append(data[pos:pos+size]);pos+=size
    return result


def unescape(data):
    out=bytearray();zeros=0;i=0
    while i<len(data):
        x=data[i]
        if zeros>=2 and x==3 and i+1<len(data) and data[i+1]<=3:
            zeros=0;i+=1;continue
        out.append(x);zeros=zeros+1 if x==0 else 0;i+=1
    return bytes(out)


def escape(data):
    out=bytearray();zeros=0
    for x in data:
        if zeros>=2 and x<=3:out.append(3);zeros=0
        out.append(x);zeros=zeros+1 if x==0 else 0
    return bytes(out)


def messages(nal):
    data=unescape(nal[2:]);pos=0;result=[]
    while pos<len(data):
        if data[pos:]==b'\x80':return result
        fields=[]
        for _ in range(2):
            value=0
            while True:
                if pos>=len(data):raise ValueError('Truncated SEI header')
                x=data[pos];pos+=1;value+=x
                if x!=255:break
            fields.append(value)
        kind,size=fields
        if pos+size>len(data):raise ValueError('Truncated SEI payload')
        result.append((kind,data[pos:pos+size]));pos+=size
    raise ValueError('Missing SEI trailing bits')


def static_nals(reference):
    with av.open(str(reference)) as c:
        s=c.streams.video[0];extra=s.codec_context.extradata
        if not extra or extra[0]!=1:raise ValueError('Requires HEVC configuration record')
        length=1+(extra[21]&3)
        packet=next(p for p in c.demux(s) if p.size)
        found={}
        for nal in unpack_nals(bytes(packet),length):
            if (nal[0]>>1)&63==39:
                for kind,payload in messages(nal):
                    if kind in (137,144):found[kind]=payload
    if set(found)!={137,144}:raise ValueError('Reference must contain mastering and content-light SEI')
    if len(found[137])!=24 or len(found[144])!=4:raise ValueError('Unexpected static HDR payload size')
    return [b'\x4e\x01'+escape(bytes([kind,len(payload)])+payload+b'\x80') for kind,payload in sorted(found.items())]


def add_static_hdr(raw, reference, output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    metadata=static_nals(reference);keyframes=0;packets=0
    with av.open(str(raw)) as src, av.open(str(output),'w') as dst:
        stream=src.streams.video[0]
        extra=stream.codec_context.extradata
        if not extra or extra[0]!=1:raise ValueError('Requires HEVC MP4 input')
        length=1+(extra[21]&3)
        out=dst.add_stream_from_template(stream)
        for p in src.demux(stream):
            if not p.size:continue
            if p.is_keyframe:
                nals=unpack_nals(bytes(p),length)
                for nal in nals:
                    if (nal[0]>>1)&63==39 and any(k in (137,144) for k,_ in messages(nal)):
                        raise ValueError('Input already has static HDR SEI; refusing duplicate metadata')
                index=next((i for i,n in enumerate(nals) if ((n[0]>>1)&63)<32),None)
                if index is None:raise ValueError('Key packet contains no video slice')
                nals[index:index]=metadata
                data=b''.join(len(n).to_bytes(length,'big')+n for n in nals)
                q=av.Packet(data);q.pts=p.pts;q.dts=p.dts;q.duration=p.duration
                q.time_base=p.time_base;q.is_keyframe=True;p=q;keyframes+=1
            p.stream=out;dst.mux(p);packets+=1
    if not keyframes:raise ValueError('No keyframes found')
    return {'packets':packets,'keyframesWithStaticHDR':keyframes,'pictureDataReencoded':False}
