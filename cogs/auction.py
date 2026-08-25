import discord
from discord.ext import commands
from discord import app_commands
import math

class AuctionCalc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="대금청구", description="빌린 메소를 갚을 때 경매장 수수료를 포함한 등록 금액을 계산합니다.")
    @app_commands.describe(amount="받을 원금 (기본 MVP 3%. 일반 5% 수수료를 적용하려면 숫자 뒤에 x를 붙이세요. 예: 100000000x)")
    async def calc_auction(self, interaction: discord.Interaction, amount: str):
        # 입력값 공백 제거 및 소문자 변환 (X 또는 x 모두 인식)
        amount = amount.strip().lower()
        is_normal = False
        
        # 맨 뒤에 'x'가 붙어있는지 확인
        if amount.endswith('x'):
            is_normal = True
            amount = amount[:-1] # 'x'를 제외한 숫자 부분만 추출
            
        try:
            # 쉼표(,)가 섞여 있어도 계산할 수 있도록 제거
            principal = int(amount.replace(',', ''))
        except ValueError:
            return await interaction.response.send_message("⚠️ 숫자만 입력해주세요! (일반 수수료 적용 시 숫자 뒤에 x 추가)", ephemeral=True)
        
        if principal <= 0:
            return await interaction.response.send_message("⚠️ 0보다 큰 금액을 입력해주세요.", ephemeral=True)

        # 수수료율 설정
        if is_normal:
            fee_rate = 0.05
            fee_name = "일반 (5%)"
        else:
            fee_rate = 0.03
            fee_name = "MVP (3%)"
            
        # 역산 공식: 원금 / (1 - 수수료율)
        listing_price = math.ceil(principal / (1 - fee_rate))
        
        # 💡 메이플 경매장 수수료 버림(내림) 처리에 따른 1메소 오차 완벽 보정
        fee = math.floor(listing_price * fee_rate)
        received = listing_price - fee
        
        # 만약 역산한 수령액이 목표 원금보다 작다면, 등록 금액을 1메소씩 올려서 맞춤
        while received < principal:
            listing_price += 1
            fee = math.floor(listing_price * fee_rate)
            received = listing_price - fee
        
        # 예쁜 결과 엠베드 생성
        embed = discord.Embed(title="🧾 경매장 대금 청구 계산기", color=discord.Color.gold())
        embed.add_field(name="목표 수령액 (원금)", value=f"**{principal:,}** 메소", inline=False)
        embed.add_field(name="적용 수수료", value=f"**{fee_name}**", inline=False)
        embed.add_field(name="경매장 등록 금액", value=f"👉 **{listing_price:,}** 메소\n*(이 금액으로 아이템을 올리라고 전달하세요!)*", inline=False)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(AuctionCalc(bot))