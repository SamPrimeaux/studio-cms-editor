import { notFound } from "next/navigation";
import { ProductPage } from "../../components/Storefront";
import { products } from "../../storefront-data";
export default async function Page({params}:{params:Promise<{slug:string}>}){ const {slug}=await params; const product=products.find(p=>p.slug===slug); if(!product) notFound(); return <ProductPage product={product}/> }
