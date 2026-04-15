from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Vendor, Order, Product
from datetime import datetime, timedelta
from sqlalchemy import func
import math
import numpy as np

analytics_bp = Blueprint('analytics', __name__)

# ==================== FORECAST SALES ====================
@analytics_bp.route('/forecast', methods=['GET'])
@jwt_required()
def forecast_sales():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if user.role != 'vendor':
        return jsonify({'message': 'Only vendors can access forecasting'}), 403
    
    vendor = user.vendor
    days_ahead = request.args.get('days', 30, type=int)
    historical_days = request.args.get('history', 90, type=int)
    
    # Get historical data
    start_date = datetime.utcnow() - timedelta(days=historical_days)
    orders = Order.query.filter_by(vendor_id=vendor.id).filter(
        Order.created_at >= start_date
    ).all()
    
    # Build daily revenue array
    daily_revenue = {}
    for order in orders:
        date_key = order.created_at.date()
        if date_key not in daily_revenue:
            daily_revenue[date_key] = 0
        daily_revenue[date_key] += order.total_amount
    
    # Simple moving average forecast
    revenues = list(daily_revenue.values())
    
    if len(revenues) < 7:
        return jsonify({
            'message': 'Not enough historical data for forecasting',
            'forecast': []
        }), 200
    
    # Calculate 7-day and 30-day moving averages
    ma_7 = sum(revenues[-7:]) / len(revenues[-7:])
    ma_30 = sum(revenues[-30:]) / len(revenues[-30:]) if len(revenues) >= 30 else ma_7
    # Simple trend calculation
    trend = (revenues[-1] - revenues[-7]) / 7 if len(revenues) >= 7 else 0
    
    # Generate forecast
    forecast = []
    base_revenue = revenues[-1]
    
    for day in range(1, days_ahead + 1):
        predicted = base_revenue + (trend * day)
        # Add some variation based on weekly pattern
        weekly_variation = 0.1 * base_revenue * math.sin(day / 7 * 2 * math.pi)
        predicted += weekly_variation
        
        forecast_date = (datetime.utcnow() + timedelta(days=day)).date()
        forecast.append({
            'date': forecast_date.isoformat(),
            'predicted_revenue': max(0, round(predicted, 2)),
            'confidence': 0.75  # ~75% confidence for simple model
        })
    
    return jsonify({
        'forecast': forecast,
        'historical_avg': round(sum(revenues) / len(revenues), 2),
        'trend': 'up' if trend > 0 else 'down',
        'trend_value': round(trend, 2)
    }), 200


# ==================== CUSTOMER INSIGHTS ====================
@analytics_bp.route('/customers', methods=['GET'])
@jwt_required()
def customer_insights():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if user.role != 'vendor':
        return jsonify({'message': 'Only vendors can access insights'}), 403
    
    vendor = user.vendor
    
    # Get all orders
    orders = Order.query.filter_by(vendor_id=vendor.id).all()
    
    # Analyze customers
    customer_stats = {}
    for order in orders:
        cust_id = order.customer_id
        if cust_id not in customer_stats:
            customer_stats[cust_id] = {
                'orders': 0,
                'total_spent': 0,
                'last_order': None
            }
        customer_stats[cust_id]['orders'] += 1
        customer_stats[cust_id]['total_spent'] += order.total_amount
        customer_stats[cust_id]['last_order'] = order.created_at.isoformat()
    
    # Identify customer segments
    loyal_customers = len([c for c in customer_stats.values() if c['orders'] > 5])
    regular_customers = len([c for c in customer_stats.values() if 2 <= c['orders'] <= 5])
    new_customers = len([c for c in customer_stats.values() if c['orders'] == 1])
    
    # Calculate retention rate (customers who ordered more than once)
    retention_rate = (loyal_customers + regular_customers) / len(customer_stats) if customer_stats else 0
    
    # Average customer lifetime value
    avg_ltv = sum([c['total_spent'] for c in customer_stats.values()]) / len(customer_stats) if customer_stats else 0
    
    return jsonify({
        'total_customers': len(customer_stats),
        'loyal_customers': loyal_customers,
        'regular_customers': regular_customers,
        'new_customers': new_customers,
        'retention_rate': round(retention_rate * 100, 2),
        'avg_lifetime_value': round(avg_ltv, 2),
        'top_customers': sorted(
            customer_stats.items(),
            key=lambda x: x[1]['total_spent'],
            reverse=True
        )[:5]
    }), 200


# ==================== PRODUCT RECOMMENDATIONS ====================
@analytics_bp.route('/recommendations', methods=['GET'])
@jwt_required()
def get_recommendations():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if user.role != 'vendor':
        return jsonify({'message': 'Only vendors can access recommendations'}), 403
    
    vendor = user.vendor
    
    products = Product.query.filter_by(vendor_id=vendor.id).all()
    
    recommendations = []
    
    for product in products:
        rec = {
            'product_id': product.id,
            'product_name': product.name,
            'current_stock': product.stock,
            'sold_count': product.sold_count,
            'price': product.price,
            'recommendations': []
        }
        
        # Stock recommendation
        if product.sold_count > 0 and product.stock == 0:
            rec['recommendations'].append('Out of stock - Consider restocking,')
        elif product.stock < 5 and product.sold_count > 0:
            rec['recommendations'].append('Low stock - Consider Making an Order,You are Low on Stock')
        
        # Price recommendation (if underperforming)
        if product.sold_count < 5:
            rec['recommendations'].append('Slow sales - Consider discount or promotion to push this product,Marketing Campaigns')
        
        # High performer
        if product.sold_count > 50:
            rec['recommendations'].append('Best seller - Increase stock levels')
        
        if rec['recommendations']:
            recommendations.append(rec)
    
    return jsonify({
        'recommendations': recommendations
    }), 200


# ==================== SEASONAL TRENDS ====================
@analytics_bp.route('/trends', methods=['GET'])
@jwt_required()
def get_trends():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if user.role != 'vendor':
        return jsonify({'message': 'Only vendors can access trends'}), 403
    
    vendor = user.vendor
    months_back = request.args.get('months', 12, type=int)
    
    # Get data for last N months
    start_date = datetime.utcnow() - timedelta(days=30*months_back)
    orders = Order.query.filter_by(vendor_id=vendor.id).filter(
        Order.created_at >= start_date
    ).all()
    
    # Group by month
    monthly_data = {}
    for order in orders:
        month_key = order.created_at.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                'revenue': 0,
                'orders': 0,
                'items': 0
            }
        monthly_data[month_key]['revenue'] += order.total_amount
        monthly_data[month_key]['orders'] += 1
        monthly_data[month_key]['items'] += sum(item.quantity for item in order.items)
    
    # Sort by month
    sorted_months = sorted(monthly_data.items())
    
    return jsonify({
        'monthly_trends': dict(sorted_months),
        'best_month': max(monthly_data.items(), key=lambda x: x[1]['revenue'])[0] if monthly_data else None,
        'worst_month': min(monthly_data.items(), key=lambda x: x[1]['revenue'])[0] if monthly_data else None
    }), 200


# ==================== HEALTH SCORE ====================
@analytics_bp.route('/health-score', methods=['GET'])
@jwt_required()
def get_health_score():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if user.role != 'vendor':
        return jsonify({'message': 'Only vendors can access health score'}), 403
    
    vendor = user.vendor
    
    orders = Order.query.filter_by(vendor_id=vendor.id).all()
    products = Product.query.filter_by(vendor_id=vendor.id).all()
    
    scores = {}
    
    # Product quality score (based on ratings)
    if products:
        scores['product_quality'] = round(np.mean([p.rating for p in products]), 2)
    else:
        scores['product_quality'] = 0
    
    # Inventory score (how well stocked)
    in_stock = len([p for p in products if p.stock > 0])
    scores['inventory'] = round((in_stock / len(products) * 100) if products else 0, 2)
    
    # Sales consistency (low variance in daily sales)
    if len(orders) > 10:
        daily_revenue = {}
        for order in orders[-30:]:
            date_key = order.created_at.date()
            if date_key not in daily_revenue:
                daily_revenue[date_key] = 0
            daily_revenue[date_key] += order.total_amount
        
        revenues = list(daily_revenue.values())
        if len(revenues) > 1:
            cv = (np.std(revenues) / np.mean(revenues)) if np.mean(revenues) > 0 else 0
            consistency = max(0, 100 - (cv * 100))
            scores['sales_consistency'] = round(consistency, 2)
        else:
            scores['sales_consistency'] = 100
    else:
        scores['sales_consistency'] = 50
    
    # Overall health (average of all scores)
    overall_health = round(np.mean(list(scores.values())), 2)
    
    return jsonify({
        'scores': scores,
        'overall_health': overall_health,
        'status': 'Excellent' if overall_health >= 80 else 'Good' if overall_health >= 60 else 'Fair' if overall_health >= 40 else 'Needs Improvement'
    }), 200
