import asyncio
import motor.motor_asyncio
async def get_latest_job():
    try:
        db = motor.motor_asyncio.AsyncIOMotorClient('mongodb://localhost:27017')['sales_intelligence']
        job = await db.jobs.find_one(sort=[('_id', -1)])
        if job:
            print(job['job_id'])
    except Exception as e:
        print(e)
asyncio.run(get_latest_job())
