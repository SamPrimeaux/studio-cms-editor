"use client";

import Link from "next/link";
import { useState } from "react";
import { archetypes, journal, products, type Product } from "../storefront-data";

function Mark() {
  return <span className="ia-mark" aria-hidden><i /><i /></span>;
}

export function StoreHeader() {
  const [open, setOpen] = useState(false);
  const [cart, setCart] = useState(false);
  return <>
    <div className="ia-dropbar">FIELD ISSUE 001 — FIRST ACCESS OPENS SOON <span>Join the pack</span></div>
    <header className="ia-header">
      <Link href="/" className="ia-logo"><Mark /><b>INNER<br/>ANIMALS</b></Link>
      <nav className={open ? "open" : ""}>
        <Link href="/shop">Shop</Link><Link href="/collections/wolf">Archetypes</Link><Link href="/journal">Field Journal</Link><Link href="/story">Our Code</Link>
      </nav>
      <div className="ia-actions"><button aria-label="Search">⌕</button><button onClick={() => setCart(true)}>Bag <span>0</span></button><button className="ia-menu" onClick={() => setOpen(!open)}>{open ? "Close" : "Menu"}</button></div>
    </header>
    {cart && <div className="ia-cart-shade" onClick={() => setCart(false)}><aside onClick={e => e.stopPropagation()}><button onClick={() => setCart(false)}>Close</button><p>YOUR FIELD BAG</p><h2>Nothing carried. Yet.</h2><span>Issue 001 is a concept collection. Join the pack for the first production release.</span><Link href="#join" onClick={() => setCart(false)}>Get first access</Link></aside></div>}
  </>;
}

export function StoreFooter() {
  return <footer className="ia-footer" id="join"><div><Mark /><h2>STAY CLOSE<br/>TO THE WILD.</h2></div><form onSubmit={e => e.preventDefault()}><label htmlFor="pack-email">Private drops, field notes and member access.</label><div><input id="pack-email" type="email" placeholder="Email address" required/><button>Join the pack →</button></div></form><nav><Link href="/shop">Shop</Link><Link href="/journal">Journal</Link><Link href="/story">Our code</Link><a href="https://instagram.com">Instagram</a></nav><small>© 2026 Inner Animals. Built in Lafayette, Louisiana. Civilized enough to function. Wild enough to matter.</small></footer>;
}

function ProductCard({ product }: { product: Product }) {
  return <article className="ia-product-card"><Link href={`/product/${product.slug}`} className="ia-product-image" style={{backgroundImage:`url(${product.image})`}}><span>{product.category}</span><em>View field spec →</em></Link><div><p>{product.name}</p><span>${product.price}</span></div><small>{product.fit} / {product.weight} / {product.color}</small></article>;
}

export function HomePage() {
  return <main className="ia-site"><StoreHeader />
    <section className="ia-hero"><div className="ia-hero-media"/><div className="ia-hero-copy"><span>FIELD ISSUE 001 / THE UNDOMESTICATED</span><h1>THE WILD<br/>IS STILL<br/>IN THERE.</h1><p>Training goods and field uniforms for people becoming harder to domesticate.</p><div><Link href="/shop">Shop the drop</Link><Link href="/story">Enter the story ↗</Link></div></div><div className="ia-hero-index">01 / 04<br/>LAFAYETTE, LA</div></section>
    <section className="ia-instinct"><header><span>SHOP BY INSTINCT</span><h2>WHAT DOES THE<br/>DAY REQUIRE?</h2></header><div>{["Train","Recover","Roam","Everyday"].map((x,i)=><Link href={`/shop?use=${x.toLowerCase()}`} key={x}><b>0{i+1}</b><span>{x}</span><em>Explore →</em></Link>)}</div></section>
    <section className="ia-drop"><div className="ia-section-head"><span>CURRENT DROP / ISSUE 001</span><h2>UNIFORMS FOR<br/>THE INNER LIFE.</h2><Link href="/shop">View all pieces →</Link></div><div className="ia-product-grid">{products.map(p=><ProductCard product={p} key={p.slug}/>)}</div></section>
    <section className="ia-manifesto"><p>THE INNER ANIMAL IS NOT AN EXCUSE.</p><h2>CIVILIZED ENOUGH<br/>TO FUNCTION.<br/><i>WILD ENOUGH</i><br/>TO MATTER.</h2><span>We make fewer things, with more weight, for people who understand that discipline and instinct are not opposites.</span><Link href="/story">Read our code</Link></section>
    <section className="ia-archetypes"><div className="ia-section-head"><span>CHOOSE YOUR ARCHETYPE</span><h2>FOUR NATURES.<br/>NO MASCOTS.</h2></div><div>{archetypes.map(a=><Link href={`/collections/${a.name.toLowerCase()}`} className={a.className} key={a.name}><span>{a.line}</span><h3>{a.name}</h3><em>Enter field →</em></Link>)}</div></section>
    <section className="ia-film"><div><span>FIELD FILM 01 / 02:17</span><button aria-label="Play concept film">▶</button><p>THE WORK BEFORE THE WORLD WAKES</p></div><article><span>PACK PROFILE</span><h2>NO AUDIENCE.<br/>NO ALGORITHM.<br/>JUST THE WORK.</h2><p>A field story from Lafayette about ritual, repetition and what a body remembers.</p><Link href="/journal/training-after-the-noise">Watch the field film →</Link></article></section>
    <section className="ia-journal"><div className="ia-section-head"><span>THE FIELD JOURNAL</span><h2>NOT CONTENT.<br/>EVIDENCE.</h2><Link href="/journal">Open the journal →</Link></div><div>{journal.map(j=><Link href={`/journal/${j.slug}`} key={j.slug}><span style={{backgroundImage:`url(${j.image})`}}/><small>{j.kind}</small><h3>{j.title}</h3><p>{j.copy}</p></Link>)}</div></section>
    <section className="ia-pack"><span>THE PACK / COMMUNITY TRANSMISSION</span><div>{[0,1,2,3,4].map(i=><figure key={i} style={{backgroundImage:`url(https://images.unsplash.com/photo-${["1583454110551-21f2fa2afe61","1571019613454-1cb2f99b2d8b","1599058917212-d750089bc07e","1534438327276-14e5300c3a48","1586401100295-7a8096fd231a"][i]}?auto=format&fit=crop&w=700&q=80)`}}><figcaption>@FIELDNOTE_{i+1}</figcaption></figure>)}</div><p>Tag <b>#INNERANIMALS</b> to enter the field log.</p></section>
    <StoreFooter />
  </main>;
}

export function ShopPage() {
  const [filter,setFilter]=useState("All");
  const filtered=filter==="All"?products:products.filter(p=>p.category===filter||p.uses.includes(filter));
  return <main className="ia-site"><StoreHeader/><section className="ia-page-hero"><span>FIELD STORE / ISSUE 001</span><h1>GEAR FOR<br/>THE WORK.</h1><p>Concept collection. Four archetypes, considered materials, no filler.</p></section><section className="ia-shop"><div className="ia-filters">{["All","Train","Recover","Roam","Everyday"].map(x=><button className={filter===x?"active":""} onClick={()=>setFilter(x)} key={x}>{x}</button>)}</div><div className="ia-product-grid">{filtered.map(p=><ProductCard product={p} key={p.slug}/>)}</div></section><StoreFooter/></main>;
}

export function ProductPage({ product }: { product: Product }) {
  const [size,setSize]=useState("L"); const [added,setAdded]=useState(false);
  return <main className="ia-site"><StoreHeader/><section className="ia-pdp"><div className="ia-pdp-image" style={{backgroundImage:`url(${product.image})`}}><span>ISSUE 001 / CONCEPT</span></div><div className="ia-pdp-info"><span>{product.category} / {product.uses.join(" + ")}</span><h1>{product.name}</h1><p className="price">${product.price}</p><p>{product.statement} A considered concept piece developed around movement, recovery and life outside the gym.</p><div className="ia-specs"><span><b>FIT</b>{product.fit}</span><span><b>WEIGHT</b>{product.weight}</span><span><b>COLOR</b>{product.color}</span></div><label>SELECT SIZE <a href="#spec">Field spec</a></label><div className="ia-sizes">{["S","M","L","XL","XXL"].map(x=><button className={size===x?"active":""} onClick={()=>setSize(x)} key={x}>{x}</button>)}</div><button className="ia-add" onClick={()=>setAdded(true)}>{added?"Added to field bag ✓":"Add to field bag"}</button><small>Concept preview — first production release and final specifications to be announced.</small></div></section><section className="ia-detail" id="spec"><span>FIELD SPEC / 001</span><h2>DESIGNED TO BE<br/>USED, NOT SAVED.</h2><div><p><b>01 / MATERIAL</b>Heavy, tactile construction selected for repeated wear and a better life after break-in.</p><p><b>02 / INTENT</b>{product.uses.join(", ")} — without looking like performance costume.</p><p><b>03 / TEST</b>Every production piece will be wear-tested by the people it was made for.</p></div></section><StoreFooter/></main>;
}

export function JournalPage() { return <main className="ia-site"><StoreHeader/><section className="ia-page-hero journal"><span>TRANSMISSIONS FROM THE FIELD</span><h1>THE FIELD<br/>JOURNAL.</h1><p>Training, materials, profiles, films, place and the inner life behind the work.</p></section><section className="ia-journal ia-journal-page"><div>{[...journal,...journal].map((j,i)=><Link href={`/journal/${j.slug}`} key={`${j.slug}-${i}`}><span style={{backgroundImage:`url(${j.image})`}}/><small>{j.kind}</small><h3>{j.title}</h3><p>{j.copy}</p></Link>)}</div></section><StoreFooter/></main> }

export function StoryPage() { return <main className="ia-site"><StoreHeader/><section className="ia-story-hero"><span>THE INNER ANIMALS CODE / 2026</span><h1>INSTINCT<br/>WITHOUT<br/><i>DISCIPLINE</i><br/>IS JUST NOISE.</h1></section><section className="ia-code"><p>Inner Animals exists in the tension between restraint and force.</p>{[["01","Use over display","We believe the finest objects get better through work, wear and memory."],["02","Fewer, heavier things","No endless catalog. Each issue earns the right to exist."],["03","The pack is practice","Community is not a follower count. It is showing up for one another."],["04","Leave proof","Train, make, travel, recover. Bring back something true."]].map(x=><article key={x[0]}><span>{x[0]}</span><h2>{x[1]}</h2><p>{x[2]}</p></article>)}</section><StoreFooter/></main> }
