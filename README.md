# Pinterest Deal Bot

Finds genuine discounts and posts them to your Pinterest boards with your affiliate links:

- **eBay UK** for 11 categories (home, tech, gifts, gym, car, clothes, pets, garden, DIY, gaming, camping): 30%+ off, new, Buy It Now, well-rated UK sellers.
- **Official retailers via Awin** for Beauty & Fragrance and Baby & Kids: 25%+ off, in stock, straight from the retailer's own product feed.
 It runs four times a day on GitHub for free, so your computer doesn't need to be on.

You do the setup below once (about an hour of your time, plus a few days waiting for approvals). After that it runs by itself. Open **SETUP-CHECKLIST.html** for the sign-up links and ready-to-paste answers for each application form.

---

## Step 1: eBay developer account (product search)

1. Sign up at **developer.ebay.com** and wait for the confirmation email.
2. Go to **Application Keysets** and create a **Production** keyset.
3. Copy the **App ID (Client ID)** and **Cert ID (Client Secret)**.

## Step 2: eBay Partner Network (your earnings)

1. Apply at **partnernetwork.ebay.com**. When it asks how you'll promote, say Pinterest.
2. Once approved, create a **campaign** (for example, "Pinterest") and copy its **Campaign ID**, a 10-digit number.
3. Add your bank details so you can be paid.

## Step 2b: Awin (beauty, fragrance, baby and kids)

You can do this later. The bot skips these two categories until it's set up.

1. Sign up as a **publisher** at **awin.com**. When asked for your promotional space, give your Pinterest profile link and choose "Social media". Approval usually takes a few days.
2. Once you're in, go to **Advertisers → Join programmes** and apply to retailers. Good ones to start with:
   - **Fragrance and beauty:** Scentsational Perfumes, The Fragrance Counter, Perfume Market UK, Beauté Boulevard. Search the directory for "beauty" and "fragrance" for more.
   - **Baby and kids:** Mamas & Papas. Search for "baby", "toys" and "kids" for more.
   Each retailer approves you separately, usually within a few days. Join plenty, because some will say no.
3. Go to **Toolbox → Create-a-Feed** and build a feed:
   - **Advertisers:** tick your approved beauty and fragrance retailers.
   - **Columns:** tick at least `aw_product_id`, `product_name`, `brand_name`, `merchant_name`, `search_price`, `rrp_price`, `product_price_old`, `in_stock`, `currency`, `aw_deep_link`, `merchant_image_url`, `large_image`.
   - **Format:** CSV. Any delimiter and compression setting works.
   - Click **Generate link** and copy the link.
4. Do the same again with your baby and kids retailers to get a second link.
5. Paste them when setup.bat asks, and add them as GitHub secrets (Step 7): `AWIN_FEED_BEAUTY` and `AWIN_FEED_KIDS`.

When you join more retailers later, regenerate the feed link to include them and update the secret.

## Step 3: Pinterest

1. Create a **business account** at pinterest.co.uk/business, or convert your personal one for free.
2. Go to **developers.pinterest.com** → My apps → **Connect app**. Describe it as "Posts curated eBay UK deals to my own boards".
3. Once the app is created, add `https://localhost/` under **Redirect URIs**.
4. Copy the **App ID** and **App secret key**.

New apps start on **Trial access**, where pins are private (only you can see them). To make them public you need **Standard access**, which means sending Pinterest a short screen recording of the bot posting a pin. Step 5 covers this.

## Step 4: Run the setup on your PC

1. Install Python from **python.org/downloads**. On the first screen, **tick "Add python.exe to PATH"**.
2. Unzip this folder somewhere easy, such as Documents.
3. Double-click **setup.bat**. It asks for your keys one at a time, checks your eBay keys work, and saves everything in a private `.env` file in the folder.
4. When it asks whether Pinterest has approved Standard access, answer **no** the first time.

## Step 5: Get Pinterest's approval (one-off)

New Pinterest apps are on Trial access, where anything created stays private. To go public:

1. Start a screen recording. On Windows, press **Win + Alt + R**, or use the Snipping Tool's video mode.
2. Double-click **demo.bat**. It finds a real eBay deal and creates a pin in Pinterest's test area. The first time, it asks for a sandbox token, which you generate on your app's page at developers.pinterest.com.
3. Stop the recording.
4. On developers.pinterest.com, open your app, click **Upgrade to Standard**, and upload the video. Describe the app as "Posts curated UK deals with affiliate links to my own Pinterest boards, a few pins per day."

## Step 6: Finish setup after approval

Double-click **setup.bat** again and answer **yes**. It will:

1. Connect your Pinterest account. Click Allow, then paste the address it lands on.
2. Create your 16 boards, or reuse any with the same name you've already made, and save their IDs into `config.yaml`.
3. Do a test run that finds deals without posting.
4. Show you every secret to paste into GitHub, with its name and value.

## Step 7: Put it on GitHub so it runs by itself

1. Create a free account at **github.com**, then a new **public** repository named `YOUR-USERNAME.github.io` (for example `dailyfindsuk.github.io`). It must be public for the free website to work. Your keys stay hidden in GitHub's encrypted Secrets, never in the code.
2. Upload every file in this folder **except `.env`**, which holds your private keys. The `.github` folder is hidden on Windows; the easiest way to include it is **GitHub Desktop**: clone the repo, copy the files in, commit, push. The included `.gitignore` already keeps `.env` out.
3. Go to **Settings → Secrets and variables → Actions → New repository secret** and add each secret setup.bat showed you:

| Secret name | What it is |
|---|---|
| `EBAY_CLIENT_ID` | eBay App ID |
| `EBAY_CLIENT_SECRET` | eBay Cert ID |
| `EPN_CAMPAIGN_ID` | eBay Partner Network campaign |
| `PINTEREST_APP_ID` | Pinterest app |
| `PINTEREST_APP_SECRET` | Pinterest app |
| `PINTEREST_REFRESH_TOKEN` | Created by setup.bat |
| `AWIN_FEED_BEAUTY` | Awin feed link (add once Awin is set up) |
| `AWIN_FEED_KIDS` | Awin feed link (add once Awin is set up) |

4. Go to **Actions → Deal bot → Run workflow** and tick **Dry run** to check it finds deals. Then run it once without the tick to post a real pin.

From then on it runs by itself at about 08:47, 12:47, 17:47 and 20:47 UK time (an hour earlier in winter).

## Your website (free, updates itself)

The `docs` folder is your website: a deals page, About page and privacy policy. Each time the bot posts, it adds the deal to the site with a number (for example #105), so people watching your videos can find it.

To switch it on: in your GitHub repo go to **Settings → Pages**, set **Source** to "Deploy from a branch", choose branch **main** and folder **/docs**, then click **Save**. After a minute your site is live at `https://YOUR-USERNAME.github.io`.

Use the site's address as your "link in bio" on Instagram, YouTube and TikTok.

## Day-to-day

- **Change what it looks for:** edit `config.yaml` (keywords, minimum discount, price range, pins per run, hashtags).
- **Add a new board later:** add it to `config.yaml`, then run setup.bat again. It reuses existing boards and only creates the new one.
- **Check it's working:** the Actions tab shows a green tick for each run. GitHub emails you if a run fails.
- **Once a year:** Pinterest's refresh token expires. Delete the `PINTEREST_REFRESH_TOKEN` line from `.env`, run setup.bat again, and update the GitHub secret. The bot's error message will tell you when it's needed.
- **Don't turn the pace up too quickly.** Start at 4 pins a day. After a month or so you could raise `pins_per_run` to 2.

## Adding Amazon later

Amazon's product API (the Creators API) requires 10 qualifying Amazon sales in the last 30 days, so it can't be automated from day one. The plan is:

1. Join Amazon Associates UK.
2. Make a separate "Amazon Finds" board and pin a few products by hand using Amazon's link tools, enough to reach those first sales.
3. Once you qualify, apply under **Associates Central → Tools → Creators API**. An Amazon module can then be added to this bot, using the same boards and schedule.

## The rules this bot follows

- Every pin is labelled **#ad** and says it contains an affiliate link.
- Pins link directly to the shop (eBay or the retailer) through the network's own tracking link. They never redirect through another site.
- Beauty and fragrance only come from official retailers, never eBay, so there's no risk of fakes. Samples, testers and refills are skipped.
- Prices are labelled "correct when posted".
- Each item is posted only once, and posts are paced to avoid Pinterest's spam filters.
- Don't use "eBay" in your Pinterest account name. eBay Partner Network doesn't allow it.
