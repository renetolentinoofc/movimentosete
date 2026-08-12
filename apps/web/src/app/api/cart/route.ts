import { cookies } from "next/headers";
import { NextResponse } from "next/server";
const origin=process.env.INTERNAL_API_URL??"http://127.0.0.1:5000";
export async function GET(){const token=(await cookies()).get("m7_cart")?.value;if(!token)return NextResponse.json({data:{items:[],subtotal_cents:0},error:null,meta:{}});const upstream=await fetch(`${origin}/api/v1/carts/view`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({cart_token:token}),cache:"no-store"});return NextResponse.json(await upstream.json(),{status:upstream.status});}
