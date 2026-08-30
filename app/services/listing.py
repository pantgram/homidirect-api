from datetime import datetime, timezone

from sqlalchemy import and_, asc, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing import Listing
from app.services.listing_image import delete_images_by_listing_id
from app.utils.errors import NotFoundError
from app.utils.serializers import get_primary_images, listing_to_dict


async def get_stats(db: AsyncSession):
    r1 = await db.execute(
        select(func.count())
        .select_from(Listing)
        .where(Listing.available == True, Listing.publication_status == "ACTIVE")
    )
    r2 = await db.execute(
        select(func.count(func.distinct(Listing.landlord_id)))
        .select_from(Listing)
        .where(Listing.publication_status == "ACTIVE")
    )
    return {"active_listings_count": r1.scalar() or 0, "property_owners_count": r2.scalar() or 0}


async def get_all_listings(db: AsyncSession):
    result = await db.execute(select(Listing).where(Listing.publication_status == "ACTIVE"))
    return result.scalars().all()


async def get_listing_by_id(db: AsyncSession, listing_id: int):
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise NotFoundError("Listing not found")
    return listing


async def get_public_listing(db: AsyncSession, listing_id: int, current_user):
    listing = await get_listing_by_id(db, listing_id)
    if listing.publication_status != "ACTIVE":
        is_owner = current_user is not None and listing.landlord_id == current_user.id
        is_admin = current_user is not None and current_user.role == "ADMIN"
        if not (is_owner or is_admin):
            raise NotFoundError("Listing not found")
    return listing


async def create_listing(
    db: AsyncSession, data: dict
):
    listing = Listing(**data)
    db.add(listing)
    await db.flush()
    await db.refresh(listing)
    return listing


async def update_listing(db: AsyncSession, listing_id: int, data: dict):
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise NotFoundError("Listing not found")

    for key, value in data.items():
        if value is not None:
            setattr(listing, key, value)
    listing.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(listing)
    return listing


async def delete_listing(db: AsyncSession, listing_id: int) -> bool:
    result = await db.execute(select(Listing).where(Listing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise NotFoundError("Listing not found")
    try:
        await delete_images_by_listing_id(db, listing_id)
    except Exception:
        pass
    await db.delete(listing)
    return True

async def search_listings(db: AsyncSession, params: dict, is_authenticated: bool = False):
    q = params.get("q")
    limit = min(params.get("limit", 15), 100 if is_authenticated else 15)
    page = params.get("page", 1)
    offset = (page - 1) * limit

    query = select(Listing)
    count_query = select(func.count()).select_from(Listing)
    conditions = [Listing.publication_status == "ACTIVE"]

    if q:
        search = f"%{q}%"
        conditions.append(
            or_(
                Listing.title_el.ilike(search),
                Listing.description_el.ilike(search),
                Listing.title_en.ilike(search),
                Listing.description_en.ilike(search),
                Listing.city.ilike(search),
                Listing.postal_code.ilike(search),
            )
        )
    if params.get("property_type"):
        conditions.append(Listing.property_type == params["property_type"])
    if params.get("city"):
        conditions.append(Listing.city.ilike(f"%{params['city']}%"))
    if params.get("region"):
        conditions.append(Listing.city.ilike(f"%{params['region']}%"))
    if params.get("country"):
        conditions.append(Listing.country.ilike(f"%{params['country']}%"))
    if params.get("min_price") is not None:
        conditions.append(Listing.price >= params["min_price"])
    if params.get("max_price") is not None:
        conditions.append(Listing.price <= params["max_price"])
    if params.get("min_bedrooms") is not None:
        conditions.append(Listing.bedrooms >= params["min_bedrooms"])
    if params.get("max_bedrooms") is not None:
        conditions.append(Listing.bedrooms <= params["max_bedrooms"])
    if params.get("min_bathrooms") is not None:
        conditions.append(Listing.bathrooms >= params["min_bathrooms"])
    if params.get("max_bathrooms") is not None:
        conditions.append(Listing.bathrooms <= params["max_bathrooms"])
    if params.get("min_area") is not None:
        conditions.append(Listing.area >= params["min_area"])
    if params.get("max_area") is not None:
        conditions.append(Listing.area <= params["max_area"])
    if params.get("floor"):
        conditions.append(Listing.floor == params["floor"])
    if params.get("min_kitchens") is not None:
        conditions.append(Listing.kitchens >= params["min_kitchens"])
    if params.get("max_kitchens") is not None:
        conditions.append(Listing.kitchens <= params["max_kitchens"])
    if params.get("min_levels") is not None:
        conditions.append(Listing.levels >= params["min_levels"])
    if params.get("max_levels") is not None:
        conditions.append(Listing.levels <= params["max_levels"])
    if params.get("elevator") is not None:
        conditions.append(Listing.elevator == params["elevator"])
    if params.get("parking_space") is not None:
        conditions.append(Listing.parking_space == params["parking_space"])
    if params.get("furnished") is not None:
        conditions.append(Listing.furnished == params["furnished"])
    if params.get("zone_type"):
        conditions.append(Listing.zone_type == params["zone_type"])
    if params.get("listing_status"):
        conditions.append(Listing.listing_status == params["listing_status"])
    if params.get("available") is not None:
        conditions.append(Listing.available == params["available"])
    if params.get("is_featured") is not None:
        conditions.append(Listing.is_featured == params["is_featured"])
    if params.get("verification_status"):
        conditions.append(Listing.verification_status == params["verification_status"])
    if params.get("date_available_from"):
        conditions.append(Listing.date_available >= params["date_available_from"])
    if params.get("date_available_to"):
        conditions.append(Listing.date_available <= params["date_available_to"])
    if params.get("min_date_built") is not None:
        conditions.append(Listing.date_built >= params["min_date_built"])
    if params.get("max_date_built") is not None:
        conditions.append(Listing.date_built <= params["max_date_built"])

    where = and_(*conditions) if conditions else None
    if where is not None:
        query = query.where(where)
        count_query = count_query.where(where)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    sort_by = params.get("sort_by", "featured")
    if sort_by == "featured":
        query = query.order_by(desc(Listing.is_featured), desc(text("CASE WHEN featured_until > NOW() THEN 1 ELSE 0 END")), desc(Listing.created_at))
    elif sort_by == "newest":
        query = query.order_by(desc(Listing.created_at))
    elif sort_by == "oldest":
        query = query.order_by(asc(Listing.created_at))
    elif sort_by == "price_asc":
        query = query.order_by(asc(Listing.price))
    elif sort_by == "price_desc":
        query = query.order_by(desc(Listing.price))
    elif sort_by == "area_asc":
        query = query.order_by(asc(Listing.area))
    elif sort_by == "area_desc":
        query = query.order_by(desc(Listing.area))

    query = query.limit(limit).offset(offset)
    results = (await db.execute(query)).scalars().all()

    listing_ids = [l.id for l in results]
    primary_images = await get_primary_images(db, listing_ids)

    items = []
    for listing in results:
        d = listing_to_dict(listing)
        d["primary_image"] = primary_images.get(listing.id)
        items.append(d)

    total_pages = (total + limit - 1) // limit
    return {
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "has_next_page": page < total_pages,
            "has_previous_page": page > 1,
        },
    }


async def get_distinct_cities(db: AsyncSession):
    result = await db.execute(
        select(Listing.city).distinct().where(
            Listing.available == True, Listing.publication_status == "ACTIVE"
        ).order_by(Listing.city)
    )
    return [r[0] for r in result.all()]


async def get_listings_by_landlord(db: AsyncSession, landlord_id: int, page: int = 1, limit: int = 15):
    offset = (page - 1) * limit
    total_result = await db.execute(select(func.count()).select_from(Listing).where(Listing.landlord_id == landlord_id))
    total = total_result.scalar() or 0

    result = await db.execute(
        select(Listing).where(Listing.landlord_id == landlord_id).order_by(desc(Listing.created_at)).limit(limit).offset(offset)
    )
    listings = result.scalars().all()

    listing_ids = [l.id for l in listings]
    primary_images = await get_primary_images(db, listing_ids)

    items = []
    for listing in listings:
        d = listing_to_dict(listing)
        d["primary_image"] = primary_images.get(listing.id)
        items.append(d)

    total_pages = (total + limit - 1) // limit
    return {
        "data": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "has_next_page": page < total_pages,
            "has_previous_page": page > 1,
        },
    }
