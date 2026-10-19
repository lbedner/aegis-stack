# About

## How did we get here?

I've been developing software professionally since 2004. It started with Java, writing server code for mobile apps in the pre-iPhone era.

My first task when I joined a new company in 2010 was to learn Ruby so I could work on a high volume, distributed audio encoding system, using drb (good times). I maintained that system for 15 years, watching it evolve, scale, and adapt through countless changes in technology and business requirements. Though there was one business requirment that never changed... It had to be up 24/7... Let's just say one can learn a lot about what could go wrong over the years

Around 2012, I picked up Python to write various ETLs, completing my core language toolkit. In that time I've seen old Java monorepos migrated to Python monorepos, then split up into real-time message-based microservices, only to be consolidated back into a monorepo.

Such is the circle of life...

## What I've Learned

You know, I was blessed to start my career working within a well-oiled machine, so I know what one looks like. Outside of pair-programming *(I didn't need someone lurking over my shoulder like a gargoyle telling me I missed a semi-colon on line 46)*, the XTreme Programming methodology the company used worked. Even that "write your tests first" shit was legit, something I never thought I would say. Test-driven development isn't just a buzzword - it's the difference between "I think this works" and "I know this works." It's why SQLite has more test code than actual code, with coverage that would make most projects weep (I've been recently having a love affair with SQLite, you'll have to excuse me).

Experience teaches you what works and what doesn't. I've seen teams paralyzed by fear of deployments, and I've seen teams that push multiple times a day with confidence. The difference? Good tooling and testing.

I've seen what happens when you don't have that foundation. When you're scared to refactor because something might break. When deployments are weekend affairs that require all hands on deck. When asking a question about the codebase gets you a shrug.

It doesn't have to be like this, and I'm tired of it being the norm.

## So I Built Aegis Stack

Eventually, I started noticing the same patterns everywhere. Every project needed the same foundation: a web API, some background jobs, maybe a database, health checks, containerization. The requirements were always slightly different, but the core components? Always the same.

Years ago, I had a boss who got it. We'd sit in one of the conference rooms dreaming about automation tools, sketching ideas, making plans. He even started working on something on the side. But that manager was long gone by the time I brought it to fruition. 

Post-pandemic, I discovered Streamlit and got tired of waiting for permission. So I built what I would later name, **[Overseer](overseer/index.md)**, myself. It actually worked - I actively used it to automate monotonous domain-specific tasks that were eating up our days.

That experience taught me what happens when you stop waiting for permission and just build the tools you need.

So Aegis Stack embodies the patterns that actually work:

- Built-in testing and health monitoring because you should know your system is working
- Battle-tested components (SQLite, FastAPI, APScheduler) because boring technology wins  
- Clean separation of concerns because future you will thank present you
- Optional complexity because not every API needs a message queue

I'm testing the shit out of this because I know how important it is. It's kind of a dream to be able to do it like this and see how far I can get.

---

At the end of the day, I just want peace. I want to write code and have the confidence to know that it works, and if something goes wrong, I don't have to spend a few days tracking it down, or only find out about it because some guy I've never heard of is having a panic attack. I've lived that life...

![Peace](images/peace.gif)

...I just want peace now.

