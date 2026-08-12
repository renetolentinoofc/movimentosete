import { cookies } from "next/headers";
import { NextRequest,NextResponse } from "next/server";
const origin=process.env.INTERNAL_API_URL??"http://127.0.0.1:5000";
export async function POST(request:NextRequest){const token=(await cookies()).get("m7_cart")?.value;if(!token)return NextResponse.json({data:null,error:{code:"cart_invalid",message:"Carrinho vazio.",fields:{}},meta:{}},{status:404});const body=await request.json();const upstream=await fetch(`${origin}/api/v1/checkout`,{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":request.headers.get("Idempotency-Key")??crypto.randomUUID()},body:JSON.stringify({...body,cart_token:token})});return NextResponse.json(await upstream.json(),{status:upstream.status});}
