from .models import *
from .forms import *
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View
from django.utils import timezone
from django.conf import settings

import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY
# Create your views here.


class HomeView(ListView):
    model = Item
    paginate_by = 10
    template_name = 'home.html'


class ItemDetailView(DetailView):
    model = Item
    template_name = 'product.html'


class OrderSummaryView(LoginRequiredMixin, View):
    def get(self, *args, **kwargs):
        # Try to get order based on the user
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            context = {
                'order': order
            }
            return render(self.request, 'order_summary.html', context)

        except ObjectDoesNotExist:
            messages.error(self.request, "You do not have an active order")
            return redirect("/")


class CheckoutView(View):
    def get(self, *args, **kwargs):
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            form = CheckoutForm()
            couponform = CouponForm()
            context = {
                'form': form,
                'couponform': couponform,
                'order': order,
                'DISPLAY_COUPON_FORM': True
            }
            return render(self.request, 'checkout.html', context)
        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect('core:checkout')

    # For debugging: print statements
    def post(self, *args, **kwargs):
        form = CheckoutForm(self.request.POST or None)
        # Try to get order based on the user
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)

            # if form is valid, enter form data into database
            if form.is_valid():
                # print(form.cleaned_data)
                # print("The form is valid")
                street_address = form.cleaned_data.get('street_address')
                apartment_address = form.cleaned_data.get('apartment_address')
                country = form.cleaned_data.get('country')
                zip = form.cleaned_data.get('zip')
                # TODO: add functionality for these fields
                # same_shipping_address = form.cleaned_data.get(
                #     'same_shipping_address')
                # save_info = form.cleaned_data.get('save_info')
                payment_option = form.cleaned_data.get('payment_option')
                billing_address = BillingAddress(
                    user=self.request.user, street_address=street_address, apartment_address=apartment_address, country=country, zip=zip)
                billing_address.save()
                order.billing_address = billing_address
                order.save()
                # TODO: add redirect to the selected payment option
                if payment_option == 'S':
                    return redirect('core:payment', payment_option='stripe')
                elif payment_option == 'P':
                    return redirect('core:payment', payment_option='paypal')
                else:
                    messages.warning(
                        self.request, 'Invalid payment option selected')
                    return redirect('core:checkout')

                    # messages.success(self.request, 'Checkout successful')
                    return redirect('core:checkout')
            messages.warning(self.request, 'Failed checkout')
            return redirect('core:checkout')

        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect("core:order-summary")
        # print(self.request.POST)


class PaymentView(View):
    # TODO: Consider editing --> billing/shipping/payment on same page
    def get(self, *args, **kwargs):
        order = Order.objects.get(user=self.request.user, ordered=False)
        if order.billing_address:
            context = {
                'order': order,
                'DISPLAY_COUPON_FORM': False
            }
            return render(self.request, "payment.html", context)
        else:
            messages.warning(self.request, 'You must enter a billing address')
            return redirect('core:checkout')

    def post(self, *args, **kwargs):
        order = Order.objects.get(user=self.request.user, ordered=False)
        token = self.request.POST.get('stripeToken')
        amount = int(order.get_total() * 100)
        # Handling errors: https://stripe.com/docs/api/errors/handling?lang=python
        try:
            # Use Stripe's library (API Call) to make requests...
            charge = stripe.Charge.create(
                amount=amount,
                currency="usd",
                source=token
            )
            # Create Payment
            payment = Payment()
            payment.stripe_charge_id = charge['id']
            payment.user = self.request.user
            payment.amount = order.get_total()
            payment.save()

            # Assign payment to order
            order.ordered = True
            for order_item in order.items.all():
                order_item.ordered = True
                order_item.save()

            order.payment = payment
            order.save()

            messages.success(
                self.request, "Your order was successfully completed!")
            return redirect("/")

        except stripe.error.CardError as e:
            # Since it's a decline, stripe.error.CardError will be caught
            body = e.json_body
            err = body.get('error', {})
            messages.warning(self.request, f"{err.get('message')}")
            return redirect("/")
        except stripe.error.RateLimitError as e:
            # Too many requests made to the API too quickly
            messages.warning(self.request, "Rate limit error")
            return redirect("/")
        except stripe.error.InvalidRequestError as e:
            # Invalid parameters were supplied to Stripe's API
            messages.warning(self.request, "Invalid parameters")
            return redirect("/")
        except stripe.error.AuthenticationError as e:
            # Authentication with Stripe's API failed
            # (maybe you changed API keys recently)
            messages.warning(self.request, "Not authenticated")
            return redirect("/")
        except stripe.error.APIConnectionError as e:
            # Network communication with Stripe failed
            messages.warning(self.request, "Network error")
            return redirect("/")
        except stripe.error.StripeError as e:
            # Display a very generic error to the user, and maybe send
            # yourself an email
            messages.warning(
                self.request, "Something went wrong. You were not charged. Please try again.")
            return redirect("/")
        except Exception as e:
            # Something else happened, completely unrelated to Stripe
            # Send an email to ourserlves
            messages.warning(
                self.request, "A serious error occured. We have been notified")
            return redirect("/")


@login_required
def add_to_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_item, created = OrderItem.objects.get_or_create(
        item=item, user=request.user, ordered=False)
    # get unordered items aka cart
    cart = Order.objects.filter(user=request.user, ordered=False)
    if cart.exists():
        order = cart[0]
        # check if order item is in the cart
        if order.items.filter(item__slug=item.slug).exists():
            order_item.quantity += 1
            order_item.save()
            messages.info(request, 'This item quantity was updated')
            return redirect("core:product", slug=slug)
        else:
            messages.info(request, 'This item was added to your cart')
            order.items.add(order_item)
            return redirect("core:product", slug=slug)
    else:
        ordered_date = timezone.now()
        order = Order.objects.create(
            user=request.user, ordered_date=ordered_date)
        order.items.add(order_item)
        messages.info(request, 'This item was added to your cart')
        return redirect("core:product", slug=slug)


@login_required
def add_in_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_item, created = OrderItem.objects.get_or_create(
        item=item, user=request.user, ordered=False)
    # get unordered items aka cart
    cart = Order.objects.filter(user=request.user, ordered=False)
    if cart.exists():
        order = cart[0]
        # check if order item is in the cart
        if order.items.filter(item__slug=item.slug).exists():
            order_item.quantity += 1
            order_item.save()
            messages.info(request, 'You added one "' +
                          order_item.item.name + '" to your cart')
            return redirect("core:order-summary")
        else:
            messages.info(request, 'This item was added to your cart')
            order.items.add(order_item)
            return redirect("core:order-summary")
    else:
        ordered_date = timezone.now()
        order = Order.objects.create(
            user=request.user, ordered_date=ordered_date)
        order.items.add(order_item)
        messages.info(request, 'This item was added to your cart')
        return redirect("core:order-summary")

# TODO: Consider deleting active orders with 0 items
#       cart = Order.objects.filter(user=request.user, ordered=False)
#       if cart.exists() and cart[0].items < 1 (???)...
#       if empty --> order_summary.html:45


@login_required
def remove_from_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    cart = Order.objects.filter(user=request.user, ordered=False)
    if cart.exists():
        order = cart[0]

        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.get(
                user=request.user, item=item, ordered=False)
            order_item.delete()
            # order.items.remove(order_item)
            messages.info(request, 'This item was removed to your cart')
            return redirect('core:product', slug=slug)
        else:
            messages.info(request, 'This item isn\'t in your cart')
            return redirect("core:product", slug=slug)
    else:
        messages.info(request, 'You do not have an active order')
        return redirect("core:product", slug=slug)


@login_required
def remove_single_item(request, slug):
    item = get_object_or_404(Item, slug=slug)
    cart = Order.objects.filter(user=request.user, ordered=False)
    if cart.exists():
        order = cart[0]

        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.get(
                user=request.user, item=item, ordered=False)
            if order_item.quantity > 1:
                order_item.quantity -= 1
                order_item.save()
                messages.info(request, 'You removed one "' +
                              order_item.item.name + '" from your cart')
            else:
                order_item.delete()
            # order.items.remove(order_item)
                messages.info(request, 'This item was removed to your cart')
            return redirect('core:order-summary')
        else:
            messages.info(request, 'This item isn\'t in your cart')
            return redirect("core:order-summary", slug=slug)
    else:
        messages.info(request, 'You do not have an active order')
        return redirect("core:order-summary", slug=slug)


@login_required
def remove_items(request, slug):
    item = get_object_or_404(Item, slug=slug)
    cart = Order.objects.filter(user=request.user, ordered=False)
    if cart.exists():
        order = cart[0]

        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.get(
                user=request.user, item=item, ordered=False)
            order_item.delete()
            # order.items.remove(order_item)
            messages.info(request, 'You removed "' +
                          order_item.item.name + '" from your cart')
            return redirect('core:order-summary')
        else:
            messages.info(request, 'This item isn\'t in your cart')
            return redirect("core:order-summary")
    else:
        messages.info(request, 'You do not have an active order')
        return redirect("core:order-summary")


@login_required
def cart(request):
    context = {
        'orderitems': OrderItem.objects.all()
    }
    return render(request, 'checkout.html', context)


def get_coupon(request, code):
    try:
        coupon = Coupon.objects.get(code=code)
        return coupon
    except ObjectDoesNotExist:
        messages.warning(request, "This coupon does not exist")
        return redirect('core:checkout')


class AddCouponView(View):
    def post(self, *args, **kwargs):
        # TODO: Coupon validations: Duplicates, number of coupons, etc...
        form = CouponForm(self.request.POST or None)
        if form.is_valid():
            try:
                code = form.cleaned_data.get('code')

                # Does the entered code create a valid Coupon instance?
                x = isinstance(get_coupon(self.request, code), Coupon)
                if not x:
                    return redirect('core:checkout')

                else:
                    order = Order.objects.get(
                        user=self.request.user, ordered=False)
                    order.coupon = get_coupon(self.request, code)
                    order.save()
                    messages.success(self.request, "Successfully added coupon")
                    return redirect('core:checkout')
            except ObjectDoesNotExist:
                messages.warning(
                    self.request, "You do not have an active order")
                return redirect('core:checkout')